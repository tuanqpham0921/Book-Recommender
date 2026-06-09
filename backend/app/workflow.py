from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from common.operation import OperationResult
import logging
import time
from typing import Any
from common.operation import format_exception


class Workflow(ABC):
    def __init__(self):
        self.name = self.workflow_ref
        self.result = OperationResult(name=self.workflow_ref)
    
    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult:
        logger = logging.getLogger(self.workflow_ref)
        time_start = time.perf_counter()
        try:
            self.result = await self.run(*args, **kwargs)
            
            # runtime failure, app still runs
            if not self.result.ok:
                logger.warning(f"Workflow failed: {self.result.message}")
                
        except Exception as e:
            # run-time failure, TODO: handle if needed
            logger.exception(f"Workflow failed: {e}")
            self.result.ok = False
            self.result.message = f"Workflow failed: {e}"
            self.result.run_time_error = format_exception(e)
        finally:
            # final formatting of the result
            self.result.name = self.workflow_ref
            self.result.duration = round(time.perf_counter() - time_start, 2)
            return self.result
    
    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> OperationResult:
        pass
    
    def add_step(self, step: OperationResult) -> None:
        self.result.steps.append(step)
        
    def format_result(self):
        self.result.message = self.success_message if self.result.ok else self.failure_message
        self.result.details = self.result.details
        
    @property
    def workflow_ref(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"