"""PlanJane — the planner. Turns a user message into an ordered plan of goals.

What decides *whether* to call it (cache, small talk, out of scope) is not in
here: that is `app/orchestration/triage.py`, one layer up.

`external.py` holds what the plan *is* (`SystemGoal`, `PlanJaneOutput`,
`ExecutionOrder`) and is the address for it; `schemas.py` holds what the LLM
fills in; `executor.py` runs. Import from this package root rather than any of
them — the split is free to move.
"""

from .executor import GoalParseRequest, PlanJaneExecutor, PlanJaneInput
from .external import ExecutionOrder, PlanJaneOutput, SystemGoal
from .schemas import MAX_SYSTEM_GOALS

__all__ = [
    "PlanJaneExecutor",
    "PlanJaneInput",
    "PlanJaneOutput",
    "ExecutionOrder",
    "GoalParseRequest",
    "SystemGoal",
    "MAX_SYSTEM_GOALS",
]
