"""The terminal answer stage — a slice with no `SPEC`.

Every other slice under `books/` exports a `NodeSpec` that `guide.py` collects
and `REGISTRY` indexes. This one deliberately does not: the planner never
selects an answer, `TaskRunnerWorkflow` attaches one per sink instead. There is
therefore nothing here for `REGISTRY` to answer about, and nothing for an eval
golden to carry.
"""

from .executor import AnswerWorkflow
from .external import AnswerInput, AnswerOutput, AnswerStep

__all__ = [
    "AnswerWorkflow",
    "AnswerInput",
    "AnswerOutput",
    "AnswerStep",
]
