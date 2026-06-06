import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any


@dataclass(slots=True)
class OperationResult:
    """Outcome of a single named check or step."""
    name: str | None = None
    ok: bool = True
    message: str | None = None
    steps: list["OperationResult"] | None = None
    details: dict[str, Any] | None = None
    duration: float | None = None
    run_time_error: Exception | None = None
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
            try:
                time_start = time.perf_counter()
                
                if log_info:
                    logger.info(f"Running task: {func_ref}")
                
                result = await func(*args, **kwargs)
                time_end = time.perf_counter()
                result.duration = time_end - time_start
                result.name = func_ref
                
                if not result.ok:
                    # runtime failure, app still runs
                    logger.warning(f"Task {func_ref} failed: {result.message}")
                elif log_info:
                    logger.info(f"Task {func_ref} : {result.message}")
                
                return result
            except Exception as e:
                logger.exception(f"Task {func_ref} failed: {e}")
                
                result = OperationResult(
                    name=func_ref,
                    ok=False,
                    message=f"Task {func_ref} failed: {e}",
                    duration=0,
                    run_time_error=e,
                )
                return result

        return wrapper

    if func is None:
        return decorator

    return decorator(func)