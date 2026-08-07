from abc import ABC, abstractmethod
from common.operation import OperationResult, Response, RuntimeErrorInfo
import asyncio
import logging
import time
from typing import Any, Generic, TypeVar


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

    def __init__(self, output_type: type[OutputT] | None = None):
        self.name = self.workflow_ref
        self.output_type = output_type
        self._called = False

        # intialize an envolope in memory to modify
        self.result: OperationResult[OutputT] = OperationResult(
            name=self.workflow_ref,
            response=Response(
                output_type=output_type.__name__ if output_type is not None else None
            ),
        )
        if output_type is not None:
            self.result.response.output = output_type()

    def add_details(self, *message):
        self.result.add_details(message)

    @property
    def output(self) -> OutputT:
        if self.result.response.output is None:
            raise RuntimeError(f"{self.workflow_ref} output was not initialized")
        return self.result.response.output

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
            await self.run(*args, **kwargs)
            self.check_output_type()

            # not runtime failure, app still runs
            if not self.result.ok:
                self.logger.warning(f"Workflow failed: {self.workflow_name}")
            else:
                self.logger.info(f"Finished workflow: {self.workflow_name}")
        except asyncio.CancelledError as e:
            # client disconnected (e.g. page refresh) mid-workflow. Stamp
            # what we have so a caller can still record a partial run, then
            # re-raise — swallowing this would stop the task from actually
            # being cancelled (see the no-`return`-in-finally note below).
            self.result.ok = False
            self.add_details("asyncio Cancelled")
            self.logger.warning(f"Workflow cancelled: {self.workflow_name}")
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
            raise
        except StepFailure as e:
            # controlled abort — the failing step's envelope already
            self.result.ok = False
            self.logger.warning(f"Workflow stopped: {e}")
            # NOTE just make the StepFailure a runtime error
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
        except Exception as e:
            self.result.ok = False
            # run-time failure: a genuine crash in run() itself
            self.logger.exception(f"Workflow failed: {e}")
            self.result.runtime_error = RuntimeErrorInfo.from_exception(e)
        finally:
            # final formatting of the result — no `return` here: a return
            # inside finally would swallow BaseExceptions (e.g. asyncio
            # cancellation) that the except clauses deliberately let through
            self.result.name = self.workflow_ref
            self.result.timing.duration = round(time.perf_counter() - time_start, 2)

        return self.result

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def run_async_step(
        self,
        function: Coroutine[Any, Any, OperationResult[Any]],
        *,
        raise_on_failure: bool = True,
    ) -> OperationResult[Any]:
        # NOTE: enable raise_on_failure = False if you want to retry
        # so the caller can capture the envolope and deal with it
        # default is True more most cases

        step_result = await function
        self.add_step(step_result)

        if step_result.ok:
            return step_result

        self.result.ok = False
        self.result.add_details(f"FAILED STEP:{step_result.name}")
        if raise_on_failure:
            # names the step only: the step's own envelope is already in
            # self.result.steps with its details and runtime_error, and this
            # string is what lands in the parent's runtime_error.message
            raise StepFailure(f"Step failed: {step_result.name}")
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
