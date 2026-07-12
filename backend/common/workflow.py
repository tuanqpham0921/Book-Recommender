from abc import ABC, abstractmethod
from common.operation import OperationResult, RuntimeErrorInfo
import asyncio
import logging
import time
from typing import Any, Callable, Generic, TypeVar


from typing import Coroutine

OutputT = TypeVar("OutputT")


class StepFailure(RuntimeError):
    """Control-flow only: raised by run_async_step to abort a workflow's
    remaining steps after a step failed. The failing step's own envelope
    already records the details (including runtime_error if it crashed), so
    __call__ logs a single summary line and does not stamp runtime_error."""


class Workflow(ABC, Generic[OutputT]):
    """One instance = one execution. self.result (and subclass output fields
    like accepted_goals) accumulate for the life of the instance and are
    never reset, so calling __call__ more than once on the same instance
    stacks the second run's output onto the first's instead of replacing it.
    Construct a new instance for every execution, including retries — the
    constructor sets up no expensive resources, so this is cheap."""

    def __init__(
        self,
        output_type: type[OutputT] | None = None,
        *,
        timeout: float | None = None,
    ):
        self.name = self.workflow_ref
        self.output_type = output_type
        self._called = False
        # bounds the whole run() call, not individual steps — see
        # run_async_step for per-step timeout/retries
        self.timeout = timeout

        # intialize an envolope in memory to modify
        self.result: OperationResult[OutputT] = OperationResult(
            name=self.workflow_ref,
            output_type=output_type.__name__ if output_type is not None else None,
        )
        if output_type is not None:
            self.result.output = output_type()

    @property
    def output(self) -> OutputT:
        if self.result.output is None:
            raise RuntimeError(f"{self.workflow_ref} output was not initialized")
        return self.result.output

    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult[OutputT]:
        if self._called:
            raise RuntimeError(
                f"{self.workflow_ref} instances are single-use — "
                "construct a new instance for each execution"
            )
        self._called = True

        time_start = time.perf_counter()
        try:
            self.logger.info(f"Running workflow: {self.workflow_name}")
            await asyncio.wait_for(self.run(*args, **kwargs), timeout=self.timeout)
            self.check_output_type()

            # not runtime failure, app still runs
            if not self.result.ok:
                self.logger.warning(f"Workflow failed: {self.result.message}")
            else:
                self.logger.info(f"Finished workflow: {self.workflow_name}")
        except asyncio.TimeoutError as e:
            # own except clause (ahead of the generic Exception one below) so
            # the message is specific instead of "Workflow failed: "
            self.result.ok = False
            self.result.message = f"Workflow timed out after {self.timeout}s"
            self.logger.warning(self.result.message)
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
            self.result.runtime_error.message = self.result.message
        except asyncio.CancelledError as e:
            # client disconnected (e.g. page refresh) mid-workflow. Stamp
            # what we have so a caller can still record a partial run, then
            # re-raise — swallowing this would stop the task from actually
            # being cancelled (see the no-`return`-in-finally note below).
            self.result.ok = False
            self.result.message = "asyncio Cancelled"
            self.logger.warning(f"Workflow cancelled: {self.workflow_name}")
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
            raise
        except StepFailure as e:
            # controlled abort — the failing step's envelope already
            self.result.ok = False
            self.logger.warning(f"Workflow stopped: {e}")
            self.result.message = str(e)
            # NOTE just make the StepFailure a runtime error
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
        except Exception as e:
            self.result.ok = False
            # run-time failure: a genuine crash in run() itself
            self.logger.exception(f"Workflow failed: {e}")
            self.result.message = f"Workflow failed: {e}"
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
        finally:
            # final formatting of the result — no `return` here: a return
            # inside finally would swallow BaseExceptions (e.g. asyncio
            # cancellation) that the except clauses deliberately let through
            self.result.name = self.workflow_ref
            self.result.duration = round(time.perf_counter() - time_start, 2)

        return self.result

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def run_async_step(
        self,
        function: Callable[[], Coroutine[Any, Any, OperationResult[Any]]],
        *,
        raise_on_failure: bool = True,
        retries: int = 1,
        timeout: float | None = None,
    ) -> OperationResult[Any]:
        """Run one step, calling `function()` fresh on each attempt.

        retries: total attempts before giving up on a *failed envelope*
        (default 1 = no retry). A bare exception raised by `function()`
        itself (no @task/envelope around it) is never retried and propagates
        immediately — see TestCrashingSteps in test_workflow.py. If
        `function` wraps a single-use Workflow instance
        (`lambda: SomeWorkflow(...)()`), it must construct a new instance on
        every call for retries to actually retry instead of hitting the
        single-use guard.
        timeout: per-attempt seconds passed to asyncio.wait_for (default
        None = no timeout).
        """
        attempts = max(retries, 1)
        step_result: OperationResult[Any]

        for attempt in range(1, attempts + 1):
            try:
                step_result = await asyncio.wait_for(function(), timeout=timeout)
            except asyncio.TimeoutError as e:
                message = f"Step timed out after {timeout}s"
                step_result = OperationResult(ok=False, message=message)
                step_result.runtime_error = RuntimeErrorInfo.from_exception(e)
                step_result.runtime_error.message = message

            step_result.retries = attempt - 1
            if step_result.ok or attempt >= attempts:
                break
            self.logger.warning(
                f"Step attempt {attempt}/{attempts} failed: {step_result.message} - retrying"
            )

        self.add_step(step_result)

        if step_result.ok:
            return step_result

        self.result.ok = False
        self.result.message = f"Step failed: {step_result.name}: {step_result.message}"
        self.result.add_details(f"FAILED STEP:{step_result.name}")
        if raise_on_failure:
            raise StepFailure(self.result.message)
        return step_result

    def add_step(self, step: OperationResult[Any]) -> None:
        if not isinstance(step, OperationResult):
            raise ValueError(f"Step is of type {type(step)} not OperationResult")

        self.result.token_usage += step.token_usage
        self.result.steps.append(step)

    @property
    def workflow_ref(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @property
    def workflow_name(self) -> str:
        return f"{type(self).__name__}:{self.result.id}"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.workflow_ref)

    def check_output_type(self) -> None:
        self.result.check_output_type()
