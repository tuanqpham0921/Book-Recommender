import logging
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
import time
from typing import Callable
import traceback
from functools import wraps

OutputT = TypeVar("OutputT")


def format_exception(error: BaseException) -> dict[str, Any]:
    """Return a JSON-friendly traceback payload for operation logs."""
    frames = traceback.extract_tb(error.__traceback__)
    formatted_frames = [
        {
            "file": frame.filename,
            "line": frame.lineno,
            "function": frame.name,
            "code": frame.line,
        }
        for frame in frames
    ]

    origin = formatted_frames[-1] if formatted_frames else None

    return {
        "type": type(error).__name__,
        "message": str(error),
        "origin": origin,
        "frames": formatted_frames,
        "traceback": traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
        ),
    }


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
                return result
            except Exception as e:
                logger.exception(f"Task {func_ref} failed: {e}")
                # in case the task is not returning a result, create a default one
                if result is None:
                    result = OperationResult(name=func_ref)
                    
                result.ok = False
                result.message = f"Task {func_ref} failed: {e}"
                result.run_time_error = format_exception(e)
            finally:
                # final formatting of the result
                result.name = func_ref
                result.duration = round(time.perf_counter() - time_start, 2)
                
                if not result.ok:
                    # runtime failure, app still runs
                    logger.warning(f"Task {func_ref} failed: {result.message}")
                elif log_info:
                    logger.info(f"Task {func_ref} : {result.message}")
                
                return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)