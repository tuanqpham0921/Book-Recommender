from abc import ABC, abstractmethod
import logging
from typing import Any, Generic, TypeVar
from typing import Coroutine

from .schemas import (
    OperationResult,
    Response,
    RuntimeErrorInfo,
)
from .exception import StepFailure
from .span import record_span
from .utils import record_call_input

OutputT = TypeVar("OutputT")


class Workflow(ABC, Generic[OutputT]):
    """One instance = one execution.

    `self.record` and subclass output fields accumulate for the life of the
    instance and are never reset, so a second `__call__` would stack onto the
    first run's output. Construct a new instance per execution, including
    retries — the constructor sets up no expensive resources.
    """

    def __init__(self, output_type: type[OutputT] | None = None):
        self.name = self.workflow_ref
        self.output_type = output_type
        self._called = False

        self.record: OperationResult[OutputT] = OperationResult(
            name=self.workflow_ref,
            response=Response(
                output_type=output_type.__name__ if output_type is not None else None
            ),
        )
        if output_type is not None:
            self.record.response.result = output_type()

        # parent_id is stamped by `parent_scope` in __call__, not here:
        # construction is not dispatch.

    def add_details(self, *message):
        self.record.add_details(*message)

    def record_input(self, *args: Any, **kwargs: Any) -> None:
        """Stamp what this workflow was called with, keyed by `run`'s parameter
        names. Never raises — see `to_record_input` for why a payload already
        recorded upstream is summarized rather than dumped again.
        """
        self.record.input = record_call_input(self.run, args, kwargs, self.logger)

    @property
    def result(self) -> OutputT:
        if self.record.result is None:
            raise RuntimeError(f"{self.workflow_ref} output was not initialized")
        return self.record.result

    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult[OutputT]:
        if self._called:
            raise RuntimeError(
                f"{self.workflow_ref} instances are single-use — "
                "construct a new instance for each execution"
            )
        self._called = True

        # before run(), so the cancel/error paths record the arguments too
        self.record_input(*args, **kwargs)

        # Timing, `parent_scope`, and the cancel/error paths — see span.py. The
        # display name is `Class:id`, not `record.name`, so concurrent runs of
        # the same workflow stay tellable apart in the logs.
        with record_span(
            self.record, self.logger, label="workflow", name=self.workflow_name
        ):
            try:
                await self.run(*args, **kwargs)
                self.check_output_type()

                # not a runtime failure, app still runs
                if not self.record.ok:
                    self.logger.warning(f"Workflow failed: {self.workflow_name}")
                else:
                    self.logger.info(f"Finished workflow: {self.workflow_name}")
            except StepFailure as e:
                # Controlled abort — the failing step's envelope is already in
                # self.record.steps. Caught here rather than left to the span so
                # it reads as a stop, not a crash.
                self.record.ok = False
                self.logger.warning(f"Workflow stopped: {e}")
                # NOTE just make the StepFailure a runtime error
                self.record.runtime_error = RuntimeErrorInfo.from_exception(e)

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
        """Await a step and abort the workflow if it failed.

        Attaching is not this method's job — the coroutine ran in this
        workflow's `parent_scope` and adopted itself, so `add_step` below is a
        no-op unless the coroutine was created outside that scope. What remains
        is the failure policy, so calling a step without this method is
        legitimate and means "I decide what a failure means myself".

        NOTE: raise_on_failure=False if you want to capture the envelope and retry.
        """
        step_result = await function
        self.record.add_step(step_result)

        if step_result.ok:
            return step_result

        self.record.ok = False
        self.record.add_details(f"FAILED STEP:{step_result.name}")
        if raise_on_failure:
            # names the step only: its envelope is already in self.record.steps
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
