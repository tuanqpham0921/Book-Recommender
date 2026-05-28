import logging
from dataclasses import dataclass, field
from typing import Any
import time
from typing import Callable

@dataclass(slots=True)
class OperationResult:
    """Outcome of a single named check or step."""
    
    ok: bool
    message: str
    steps: list["OperationResult"] | None = None
    details: dict[str, Any] | None = None
    duration: float | None = None
    name: str | None = None
    
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


def task(func: Callable[..., Any]) -> Callable[..., Any]:
    async def wrapper(*args: Any, **kwargs: Any) -> OperationResult:
        try:
            time_start = time.perf_counter()
            result = await func(*args, **kwargs)
            time_end = time.perf_counter()
            result.duration = time_end - time_start
            result.name = func.__name__
        except Exception as e:
            # raise e
            result = OperationResult(
                name=func.__name__,
                ok=False,
                message=f"Task {func.__name__} failed: {e}",
                duration=0,
                run_time_error=e,
            )
        finally:
            return result
        
    return wrapper