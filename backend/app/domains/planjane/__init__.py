"""PlanJane — the planner. Turns a user message into an ordered plan of goals.

What decides *whether* to call it (cache, small talk, out of scope) is not in
here: that is `app/orchestration/triage.py`, one layer up.
"""

from .executor import (
    ExecutionOrder,
    GoalParseRequest,
    MAX_SYSTEM_GOALS,
    PlanJaneExecutor,
    PlanJaneOutput,
    SystemGoal,
)

__all__ = [
    "PlanJaneExecutor",
    "PlanJaneOutput",
    "ExecutionOrder",
    "GoalParseRequest",
    "SystemGoal",
    "MAX_SYSTEM_GOALS",
]
