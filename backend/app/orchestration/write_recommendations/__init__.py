"""The turn's reply-writer — one stage, not a node.

Exports no `SPEC` and no request schema (2026-09-08): the planner cannot pick
this, so there is nothing for the registry to index and nothing for a catalog
entry to describe. `Orchestrator` constructs the executor directly, once, after
the task runner. See `executor.py` for why.
"""

from .executor import GenerateRecommendationsExecutor
from .external import (
    GenerationResult,
    RecommendationsInput,
    RecommendationsOutput,
    SourceBlock,
    TextBlock,
)

__all__ = [
    "GenerateRecommendationsExecutor",
    "GenerationResult",
    "RecommendationsInput",
    "RecommendationsOutput",
    "SourceBlock",
    "TextBlock",
]
