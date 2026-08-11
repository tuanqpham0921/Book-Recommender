from abc import ABC, abstractmethod
import asyncio
import logging
import time
from typing import Any, Generic, TypeVar
from typing import Coroutine

from .schemas import (
    OperationResult,
    WorkFlowOperationResult,
    Response,
    RuntimeErrorInfo,
)
from .exception import StepFailure
from .utils import bind_call_args, now_iso, to_record_input

OutputT = TypeVar("OutputT")


class Workflow(ABC, Generic[OutputT]):
    """One instance = one execution. self.record (and subclass output
    fields like accepted_goals) accumulate for the life of the instance and
    are never reset, so calling __call__ more than once on the same instance
    stacks the second run's output onto the first's instead of replacing it.
    Construct a new instance for every execution, including retries — the
    constructor sets up no expensive resources, so this is cheap."""

    def __init__(self, output_type: type[OutputT] | None = None):
        self.name = self.workflow_ref
        self.output_type = output_type
        self._called = False

        # intialize a record envolope in memory to modify. The tree-shaped
        # envelope, not the leaf one: a Workflow is by definition the thing
        # that accumulates steps.
        self.record: WorkFlowOperationResult[OutputT] = WorkFlowOperationResult(
            name=self.workflow_ref,
            response=Response(
                output_type=output_type.__name__ if output_type is not None else None
            ),
        )
        if output_type is not None:
            self.record.response.result = output_type()

    def add_details(self, *message):
        self.record.add_details(*message)

    def record_input(self, *args: Any, **kwargs: Any) -> None:
        """Stamp what this workflow was called with onto its own envelope.

        Keyed by `run`'s parameter names, so the record reads the same whether
        the caller passed positionally or by keyword. Values that can
        summarize themselves do — see `to_record_input` for why a payload
        already recorded upstream should not be dumped again here.

        Never raises. Bookkeeping that can take down the run it is describing
        is worse than a missing field, and `to_summary` is app code this
        library does not control.
        """
        try:
            arguments = bind_call_args(self.run, args, kwargs)
            self.record.input = {
                name: value for name, value in arguments.items()
            } or None
        except Exception:
            self.logger.warning(
                f"Could not record input for {self.workflow_name}", exc_info=True
            )

    @property
    def result(self) -> OutputT:
        # self.record is this Workflow's WorkFlowOperationResult envelope; .result
        # on that is its own shorthand property for the payload
        # (WorkFlowOperationResult.response.result)
        if self.record.result is None:
            raise RuntimeError(f"{self.workflow_ref} output was not initialized")
        return self.record.result

    async def __call__(
        self, *args: Any, **kwargs: Any
    ) -> WorkFlowOperationResult[OutputT]:
        if self._called:
            raise RuntimeError(
                f"{self.workflow_ref} instances are single-use — "
                "construct a new instance for each execution"
            )
        self._called = True

        # Stamped before run(), not after: the call that crashed is the one
        # worth knowing the arguments of, and this way the cancel/error paths
        # below record them too.
        self.record_input(*args, **kwargs)

        # Re-stamped here, not left at what __init__ defaulted it to: the
        # envelope is built at construction, which for a node executor is
        # before the runner dispatches it. `start_time` should mean "when the
        # run began" — the same instant `duration` is measured from, which is
        # what lets `end_time` be derived from the two (see Time.end_time).
        self.record.timing.start_time = now_iso()
        time_start = time.perf_counter()
        try:
            self.logger.info(f"Running workflow: {self.workflow_name}")
            await self.run(*args, **kwargs)
            self.check_output_type()

            # not runtime failure, app still runs
            if not self.record.ok:
                self.logger.warning(f"Workflow failed: {self.workflow_name}")
            else:
                self.logger.info(f"Finished workflow: {self.workflow_name}")
        except asyncio.CancelledError as e:
            # client disconnected (e.g. page refresh) mid-workflow. Stamp
            # what we have so a caller can still record a partial run, then
            # re-raise — swallowing this would stop the task from actually
            # being cancelled (see the no-`return`-in-finally note below).
            self.record.ok = False
            self.add_details("asyncio Cancelled")
            self.logger.warning(f"Workflow cancelled: {self.workflow_name}")
            self.record.runtime_error = RuntimeErrorInfo.from_exception(e)
            raise
        except StepFailure as e:
            # controlled abort — the failing step's envelope already
            self.record.ok = False
            self.logger.warning(f"Workflow stopped: {e}")
            # NOTE just make the StepFailure a runtime error
            self.record.runtime_error = RuntimeErrorInfo.from_exception(e)
        except Exception as e:
            self.record.ok = False
            # run-time failure: a genuine crash in run() itself
            self.logger.exception(f"Workflow failed: {e}")
            self.record.runtime_error = RuntimeErrorInfo.from_exception(e)
        finally:
            # final formatting of the result — no `return` here: a return
            # inside finally would swallow BaseExceptions (e.g. asyncio
            # cancellation) that the except clauses deliberately let through
            self.record.name = self.workflow_ref
            self.record.timing.duration = round(time.perf_counter() - time_start, 2)

        return self.record

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def run_async_step(
        self,
        function: Coroutine[Any, Any, OperationResult[Any]],
        *,
        raise_on_failure: bool = True,
    ) -> OperationResult[Any]:
        # typed on the base envelope both ways: a step is a step whether a
        # @task returned a leaf or a nested Workflow returned its own tree, and
        # nothing here reads `steps`
        #
        # NOTE: enable raise_on_failure = False if you want to retry
        # so the caller can capture the envolope and deal with it
        # default is True more most cases

        step_result = await function
        self.record.add_step(step_result)

        if step_result.ok:
            return step_result

        self.record.ok = False
        self.record.add_details(f"FAILED STEP:{step_result.name}")
        if raise_on_failure:
            # names the step only: the step's own envelope is already in
            # self.record.steps with its details and runtime_error, and this
            # string is what lands in the parent's runtime_error.message
            raise StepFailure(f"Step failed: {step_result.name}")
        return step_result

    @property
    def workflow_ref(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @property
    def workflow_name(self) -> str:
        return f"{type(self).__name__}:{self.record.id}"

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.workflow_ref)

    def check_output_type(self) -> None:
        self.record.check_output_type()
