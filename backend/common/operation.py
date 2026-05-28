import logging
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of a single named check or step."""
    name: str
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationReport:
    """Collection of operation results with aggregate pass/fail state."""
    name: str
    checks: list[OperationResult] = field(default_factory=list)
    message: str = ""
    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def get(self, name: str) -> OperationResult | None:
        return next((check for check in self.checks if check.name == name), None)

    def print(self, indent: int = 0) -> None:
        prefix = "  " * indent
        
        print("----------------------------------------------------------------------------------------------")
        print(f"{prefix} {self.name}: {self.message}")
        for child in self.checks:
            print(f"{prefix}  {child.name}: {child.message}")
            if child.details:
                print(f"{prefix}    details: {child.details}")
        print("----------------------------------------------------------------------------------------------")