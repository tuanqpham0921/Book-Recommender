import logging
from dataclasses import dataclass, field
from typing import Any
import time
from typing import Callable

@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of a single named check or step."""
    name: str
    ok: bool
    message: str
    steps: list["OperationResult"] | None = None
    details: dict[str, Any] | None = None
    
    def print(self, indent: int = 0) -> None:
        prefix = "  " * indent
        print(f"{prefix}{'✅' if self.ok else '❌'} {self.name}: {self.message}")
        if self.steps:
            for step in self.steps:
                step.print(indent + 1)



def task(func: Callable[..., Any]) -> Callable[..., Any]:
    async def wrapper(*args: Any, **kwargs: Any) -> OperationResult:
        try:
            time_start = time.perf_counter()
            result = await func(*args, **kwargs)
            time_end = time.perf_counter()
            cleaned_result = OperationResult(
                name=func.__name__,
                ok=True,
                message=f"✅ Task {func.__name__} completed in {time_end - time_start:.2f} seconds",
                steps=[result] if result else None,
            )
        except Exception as e:
            cleaned_result = OperationResult(
                name=func.__name__,
                ok=False,
                message=f"❌ Task {func.__name__} failed: {e}",
            )
        finally:
            cleaned_result.print()
            return cleaned_result
        
    return wrapper