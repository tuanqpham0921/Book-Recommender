import logging
from dataclasses import dataclass, field
from typing import Any
import time
from typing import Callable
import traceback
from functools import wraps


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
class OperationResult:
    """Outcome of a single named check or step."""
    name: str | None = None
    ok: bool = True
    message: str | None = None
    steps: list["OperationResult"] = field(default_factory=list)
    details: dict[str, Any] | None = None
    duration: float | None = None
    run_time_error: dict[str, Any] | Exception | None = None
    result: Any | None = None
    
    
    
    def print(self, indent: int = 0) -> None:
        prefix = "    " * indent
        print(f"{prefix}{'✅' if self.ok else '❌'} {self.name}: {self.message}")
        if self.steps:
            for step in self.steps:
                step.print(indent + 1)
        if self.details:
            print(f"{prefix}Details: {self.details}")
        if self.result:
            print(f"{prefix}Result: {self.result}")
        if self.duration:
            print(f"{prefix}Duration: {self.duration} seconds")
            
def task(
    func: Callable[..., Any] | None = None,
    *,
    log_info: bool = True,
) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> OperationResult:
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