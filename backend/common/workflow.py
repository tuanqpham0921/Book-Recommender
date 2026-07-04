from abc import ABC, abstractmethod
from common.operation import OperationResult
import logging
import time
from typing import Any, Generic, TypeVar
import traceback


from typing import Coroutine

OutputT = TypeVar("OutputT")

class Workflow(ABC, Generic[OutputT]):
    def __init__(self, output_type: type[OutputT] | None = None):
        self.name = self.workflow_ref
        self.output_type = output_type
        self.result: OperationResult[OutputT] = OperationResult(
            name=self.workflow_ref,
            output_type=output_type.__name__ if output_type is not None else None,
        )
        self.stop_on_failure = True
        if output_type is not None:
            self.result.output = output_type()
        
    @property
    def output(self) -> OutputT:
        if self.result.output is None:
            raise RuntimeError(f"{self.workflow_ref} output was not initialized")
        return self.result.output

    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult[OutputT]:
        time_start = time.perf_counter()
        try:
            self.logger.info(f"Running workflow: {self.workflow_name}")
            await self.run(*args, **kwargs)
            self.check_output_type()

            # not runtime failure, app still runs
            if not self.result.ok:
                self.logger.warning(f"Workflow failed: {self.result.message}")

        except Exception as e:
            # run-time failure, TODO: handle if needed
            self.logger.exception(f"Workflow failed: {e}")
            self.result.ok = False
            self.result.message = f"Workflow failed: {e}"
            self.result.run_time_error = traceback.format_exception(e)
        finally:
            # final formatting of the result
            self.result.name = self.workflow_ref
            self.result.duration = round(time.perf_counter() - time_start, 2)

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
        result = await function
        return self.add_step(result, raise_on_failure=raise_on_failure)

    def run_step(
        self,
        result: OperationResult[Any],
        *,
        raise_on_failure: bool = True,
    ) -> OperationResult[Any]:
        return self.add_step(result, raise_on_failure=raise_on_failure)

    def add_step(
        self, step: OperationResult[Any], *, raise_on_failure: bool = True
    ) -> OperationResult[Any]:
        # if isinstance(step, OperationResult[Any]):
        #     raise ValueError(f"Step is of type {type(step)} not OperationResult")
        
        self.result.steps.append(step)

        if step.ok:
            return step

        self.result.ok = False
        self.result.message = f"Step failed: {step.name}"
        self.logger.warning(f"🛑 {step.name} FAILED: {step.message}")

        if raise_on_failure:
            raise RuntimeError(f"🛑 {step.name} FAILED: {step.message}")

        return step

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
