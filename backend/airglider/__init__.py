"""airglider — result envelopes and workflow scaffolding for async pipelines.

Everything a consumer needs is re-exported here, so application code imports
`from airglider import ...` and never reaches into `airglider.src.*`. That
indirection is the whole point of the package boundary: the internal module
layout stays free to move without touching a caller.

The package imports nothing from its host application, so it can be lifted out
as a standalone distribution. The one thing a host is expected to own is the
model price table in `airglider.src.config` — see that module's docstring.
"""

from .src.task import task
from .src.base_glider import Workflow
from .src.exception import StepFailure
from .src.schemas import (
    ModelUsage,
    OperationResult,
    Response,
    RuntimeErrorInfo,
    Time,
    TokenUsage,
)
from .src.config import (
    MODEL_PRICES,
    PER_MILLION,
    PRICES_CHECKED_ON,
    UNKNOWN_MODEL,
    ModelPrice,
    cost_of,
    price_for,
)
from .src.utils import (
    now_iso,
    remove_empty_values,
    strip_zero_token_usage,
    to_serializable,
    uuid_8,
)

__all__ = [
    # scaffolding
    "Workflow",
    "task",
    "StepFailure",
    # envelopes
    "OperationResult",
    "Response",
    "Time",
    # usage / errors
    "TokenUsage",
    "ModelUsage",
    "RuntimeErrorInfo",
    # pricing
    "MODEL_PRICES",
    "ModelPrice",
    "PER_MILLION",
    "PRICES_CHECKED_ON",
    "UNKNOWN_MODEL",
    "cost_of",
    "price_for",
    # serialization / identity
    "now_iso",
    "uuid_8",
    "to_serializable",
    "remove_empty_values",
    "strip_zero_token_usage",
]
