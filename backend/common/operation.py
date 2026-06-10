import logging
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
import time
from typing import Callable
from functools import wraps

from common.utils import format_exception

OutputT = TypeVar("OutputT")


@dataclass(slots=True)
class OperationResult(Generic[OutputT]):
    """Outcome of a single named check or step."""
    name: str | None = None
    ok: bool = True
    message: str | None = None
    steps: list["OperationResult[Any]"] = field(default_factory=list)
    details: dict[str, Any] | None = None
    duration: float | None = None
    run_time_error: dict[str, Any] | Exception | None = None
    
    result: OutputT | None = None
    output_type: type[OutputT] | None = None
    
    def check_output_type(self) -> None:
        if self.result is None or self.output_type is None:
            return
        
        if self.output_type and not isinstance(self.result, self.output_type):
            raise TypeError(f"Result {self.result} is of type {type(self.result)} not of type {self.output_type}")
            
def task(
    func: Callable[..., Any] | None = None,
    *,
    log_info: bool = True,
) -> Callable[..., Any]:
    """ for single step operations (for multiple steps, use Workflow)"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            time_start = time.perf_counter()
            result = None
            try:
                if log_info:
                    logger.info(f"Running task: {func_ref}")
                
                result = await func(*args, **kwargs)
                result.name = func_ref
                result.duration = round(time.perf_counter() - time_start, 2)
                return result
            except Exception as e:
                # in case the task is not returning a result, create a default one
                if result is None:
                    result = OperationResult(name=func_ref)
                    
                result.ok = False
                result.message = f"Task {func_ref} failed: {e}"
                result.run_time_error = format_exception(e)
                result.duration = round(time.perf_counter() - time_start, 2)
                logger.exception(f"Task {func_ref} failed: {e}")
                # or raise the exception
                return result
                
        return wrapper

    if func is None:
        return decorator

    return decorator(func)

@task
async def run_tool_call(tool_call, **kwargs) -> OperationResult[Any]:
    tool_name = tool_call.function.name
    
    tool_instance = tool_call.function.parsed_arguments
    output = await tool_instance(**kwargs)
    return OperationResult(
        name=tool_name,
        ok=True,
        message=f"{tool_name} completed successfully",
        result=output,
        output_type=type(output),
    )