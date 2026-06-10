from abc import ABC, abstractmethod
from common.operation import OperationResult
import logging
import time
from typing import Any, Generic, TypeVar
from common.utils import format_exception
from clients.schemas import OpenAIChatRequest
from app.common.messages import BaseMessage
from app.common.sse_stream import SSEStream

OutputT = TypeVar("OutputT")

class Workflow(ABC, Generic[OutputT]):
    def __init__(self, output_type: type[OutputT] | None = None):
        self.name = self.workflow_ref
        self.result: OperationResult[OutputT] = OperationResult(
            name=self.workflow_ref,
            output_type=output_type,
        )
        self.stop_on_failure = True
    
    async def __call__(self, *args: Any, **kwargs: Any) -> OperationResult[OutputT]:
        time_start = time.perf_counter()
        try:
            await self.run(*args, **kwargs)
            self.check_output_type()
            
            # runtime failure, app still runs
            if not self.result.ok:
                self.logger.warning(f"Workflow failed: {self.result.message}")
                
        except Exception as e:
            # run-time failure, TODO: handle if needed
            self.logger.exception(f"Workflow failed: {e}")
            self.result.ok = False
            self.result.message = f"Workflow failed: {e}"
            self.result.run_time_error = format_exception(e)
        finally:
            # final formatting of the result
            self.result.name = self.workflow_ref
            self.result.duration = round(time.perf_counter() - time_start, 2)
            
            return self.result
    
    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> None:
        pass
    
    def add_step(self, step: OperationResult[Any]) -> OperationResult[Any]:
        self.result.steps.append(step)
        
        if step.ok:
            return step
        
        self.result.ok = False
        self.result.message = f"Step failed: {step.name}"
        self.logger.warning(f"🛑 {step.name} FAILED: {step.message}")
        
        if self.stop_on_failure:
            raise RuntimeError(f"🛑 {step.name} FAILED: {step.message}")
        
        return step
                
    def format_result(self):
        self.result.message = self.success_message if self.result.ok else self.failure_message
        self.result.details = self.result.details
        
    @property
    def workflow_ref(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"
    
    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.workflow_ref)
    
    def check_output_type(self) -> None:
        self.result.check_output_type()
        
    async def generate_user_response(self,
                                     messages: list[BaseMessage],
                                     prompt: str,
                                     sse_stream: SSEStream) -> OperationResult[Any]:
        req = OpenAIChatRequest(
            prompt=prompt,
            messages=messages,
            sse_stream=sse_stream,
            temperature=0.7,
            top_p=1.0,
        )
        result = await self.llm_client.execute_new(req)
        return self.add_step(result)