import logging
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
import time
from typing import Callable
from functools import wraps
import traceback

from common.utils import now_iso, uuid_8

OutputT = TypeVar("OutputT")


@dataclass(slots=True)
class OperationResult(Generic[OutputT]):
    """Outcome of a single named check or step."""
    id: str = field(default_factory=lambda: f"op_{uuid_8()}")
    start_time: str = field(default_factory=now_iso)
    name: str | None = None
    
    ok: bool = True
    message: str | None = None
    steps: list["OperationResult[Any]"] = field(default_factory=list)
    details: dict[str, Any] | None = None
    
    output: OutputT | None = None
    output_type: type[OutputT] | None = None
    
    run_time_error: dict[str, Any] | Exception | None = None
    duration: float | None = None
    
    def check_output_type(self) -> None:
        if self.output is None or self.output_type is None:
            return
        
        if self.output_type and not isinstance(self.output, self.output_type):
            raise TypeError(f"Output {self.output} is of type {type(self.output)} not of type {self.output_type}")
            
def task(
    func: Callable[..., Any] | None = None,
    *,
    log_info: bool = True,
) -> Callable[..., Any]:
    """For single-step operations (for multiple steps, use Workflow)."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> OperationResult[Any]:
            logger = logging.getLogger(func.__module__)
            func_ref = f"{func.__module__}.{func.__qualname__}"
            time_start = time.perf_counter()
            try:
                if log_info:
                    logger.info(f"Running task: {func_ref}")
                
                output = await func(*args, **kwargs)
                
                # custom operation result retuned from the task
                # the task must validate ok and message
                if isinstance(output, OperationResult):
                    output.name = func_ref
                    output.duration = round(time.perf_counter() - time_start, 2)
                    return output
                
                # task is not returning an operation result, create a default one
                # no run time error is recorded, so the task is considered successful
                result = OperationResult(name=func_ref, output=output, output_type=type(output))
                result.duration = round(time.perf_counter() - time_start, 2)
                result.ok = True
                result.message = f"Task {func_ref} completed successfully"
                result.details = {"output_note": "output is not an operation result, creating a default one"}
                return result
            except Exception as e:
                # run time error is recorded, so the task is considered failed
                result = OperationResult(name=func_ref)
                result.ok = False
                result.message = f"Task {func_ref} failed: {e}"
                result.run_time_error = traceback.format_exception(e)
                result.duration = round(time.perf_counter() - time_start, 2)
                return result
                
        return wrapper

    if func is None:
        return decorator

    return decorator(func)