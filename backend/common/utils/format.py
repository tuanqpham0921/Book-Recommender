# Utilies to help with serlizing and cleaning values
from typing import Any
from pydantic import BaseModel

from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path


def to_serializable(value: Any) -> Any:
    """Convert app/Pydantic objects into readable JSON-compatible values."""
    if isinstance(value, type):
        return value.__name__

    if isinstance(value, BaseModel):
        # model_dump() serializes list[BaseClass] fields using the declared type,
        # stripping subclass fields and losing private attrs before recursion.
        # Iterating via getattr preserves actual runtime types so recursive calls
        # see the full subclass schema and private attrs.
        data = {
            name: to_serializable(getattr(value, name))
            for name, info in type(value).model_fields.items()
            if not info.exclude
        }
        # model_fields only covers declared fields, so on extra="allow" models
        # (e.g. the OpenAI SDK's) anything the API returned that the schema
        # doesn't know about sits in __pydantic_extra__ and would be dropped.
        if value.__pydantic_extra__:
            for k, v in value.__pydantic_extra__.items():
                data[k] = to_serializable(v)
        if value.__pydantic_private__:
            for k, v in value.__pydantic_private__.items():
                data[k] = to_serializable(v)
        return data

    if is_dataclass(value):
        return {
            field.name: to_serializable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, BaseException):
        return {
            "type": type(value).__name__,
            "message": str(value),
        }

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_serializable(item) for item in value]

    return value


def remove_empty_values(value: Any) -> Any:
    """Drop None, empty strings, and empty collections from jsonable data."""
    if isinstance(value, dict):
        cleaned = {key: remove_empty_values(item) for key, item in value.items()}
        return {
            k: v
            for k, v in cleaned.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    if isinstance(value, list):
        cleaned = [remove_empty_values(item) for item in value]
        return [
            item
            for item in cleaned
            if item is not None and item != "" and item != [] and item != {}
        ]

    return value


def strip_zero_token_usage(value: Any) -> Any:
    """Drop a `token_usage` dict whose remaining fields are all exactly zero.

    Scoped to that one key by name rather than folded into
    `remove_empty_values`: 0 and False survive that function on purpose
    (`ok: False`, `num_books: 0` are real answers, not absence — see
    test_preserves_zero_and_false), so a generic "drop zero scalars" rule
    would be wrong there. `token_usage` is the one place an all-zero shape
    really does mean "nothing to report" — a DB check or combine-tier step
    that made no LLM call — so it gets a name-scoped rule instead of a
    general one.

    Dev-log readability only. Never apply this before the DB write: an
    envelope that genuinely spent $0 must still serialize `cost_usd: 0.0`
    there, not vanish into the same shape as a pre-cost-tracking row with no
    `token_usage` key at all — that distinction is what lets
    evals/report.py average real zeros without quietly counting unknown
    spend as free (see `token_counts`'s docstring). Run this only after
    `remove_empty_values`, on the copy written to the local dev file.
    """
    if isinstance(value, dict):
        cleaned = {key: strip_zero_token_usage(item) for key, item in value.items()}
        return {
            key: item
            for key, item in cleaned.items()
            if not (
                key == "token_usage"
                and isinstance(item, dict)
                and item
                and all(n == 0 for n in item.values())
            )
        }

    if isinstance(value, list):
        return [strip_zero_token_usage(item) for item in value]

    return value
