from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from common.operation import OperationResult
import logging
import time
from typing import Any
from common.operation import format_exception

@dataclass
class Workflow(ABC):
    name: str
    result: OperationResult = field(default_factory=OperationResult)
    
    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult:
        logger = logging.getLogger(self.name)
        time_start = time.perf_counter()
        try:
            
            self.result = await self.run(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Workflow {self.name} failed: {e}")
            self.result.ok = False
            self.result.message = f"Workflow {self.name} failed: {e}"
            self.result.run_time_error = format_exception(e)
        finally:
            # final formatting of the result
            self.result.name = self.name
            self.result.duration = round(time.perf_counter() - time_start, 2)
            
            if not self.result.ok:
                # runtime failure, app still runs
                logger.warning(f"Workflow {self.name} failed: {self.result.message}")
            return self.result
    
    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> OperationResult:
        pass
    
    def add_step(self, step: OperationResult) -> None:
        self.result.steps.append(step)
        
        
    def format_result(self):
        self.result.message = self.success_message if self.result.ok else self.failure_message
        self.result.details = self.result.details