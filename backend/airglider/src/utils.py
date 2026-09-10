"""Serialization and identity helpers for record trees.

Self-contained on purpose: airglider imports nothing from the host app, which
re-exports these (see `common/utils/`) rather than keeping a second copy.
"""

import inspect
import logging
import uuid
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel


def now_iso() -> str:
    """The current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def uuid_8() -> str:
    return str(uuid.uuid4())[:8]


def to_serializable(value: Any) -> Any:
    """Convert app/Pydantic objects into readable JSON-compatible values."""
    if isinstance(value, type):
        return value.__name__

    if isinstance(value, BaseModel):
        # not model_dump(): it serializes list[BaseClass] fields by the declared
        # type, stripping subclass fields and private attrs. getattr keeps the
        # runtime type so recursion sees the full schema.
        data = {
            name: to_serializable(getattr(value, name))
            for name, info in type(value).model_fields.items()
            if not info.exclude
        }
        # model_fields misses what extra="allow" models (e.g. the OpenAI SDK's)
        # park in __pydantic_extra__.
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


def bind_call_args(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """A call's arguments keyed by their parameter names, so `f(x)` and
    `f(arg=x)` record identically. A leading `self`/`cls` is dropped.

    Returns `{}` rather than raising on a bad signature match — the call itself
    is about to raise a better error.
    """
    try:
        parameters = inspect.signature(func).parameters
        bound = inspect.signature(func).bind(*args, **kwargs)
    except (TypeError, ValueError):
        return {}

    # no apply_defaults(): the record says what the caller passed
    arguments = dict(bound.arguments)
    first = next(iter(parameters), None)
    if first in ("self", "cls"):
        arguments.pop(first, None)
    return arguments


def to_record_input(value: Any) -> Any:
    """`to_serializable` for `OperationResult.input`, with two differences:

    1. `to_summary()` wins — a node's input carries the previous node's output,
       already held in full by its own envelope; re-dumping would grow the trace
       with the square of the plan's depth.
    2. The result is always JSON-encodable; anything left over becomes
       `<TypeName>`. Many `@task` call sites take a live handle (a DB session, a
       client), and one reaching the envelope breaks the JSONB insert.
    """
    # TODO: this should be use for summary record only
    # don't always put it to summary when first added
    
    # to_summary = getattr(value, "to_summary", None)
    # if callable(to_summary):
    #     return to_summary()

    if isinstance(value, BaseModel):
        return {
            name: to_record_input(getattr(value, name))
            for name, info in type(value).model_fields.items()
            if not info.exclude
        }

    if isinstance(value, dict):
        return {str(key): to_record_input(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_record_input(item) for item in value]

    serialized = to_serializable(value)
    if serialized is None or isinstance(serialized, (str, bool, int, float)):
        return serialized
    if isinstance(serialized, (dict, list)):
        return serialized

    # a live handle, or anything with no serializable form
    return f"<{type(value).__name__}>"


def record_call_input(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """What a call was made with, keyed by parameter name — or None.

    Both `@task` and `Workflow.__call__` compute this before the call, so the
    error and cancel paths record the arguments too. Never raises: bookkeeping
    must not take down the work it describes.
    """
    try:
        arguments = bind_call_args(func, args, kwargs)
        return {
            name: to_record_input(value) for name, value in arguments.items()
        } or None
    except Exception:
        logger.warning(f"Could not record input for {func.__qualname__}", exc_info=True)
        return None


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

    Name-scoped, not a general "drop zero scalars" rule: 0 and False survive
    `remove_empty_values` on purpose, and `token_usage` is the one key where
    all-zero means "no LLM call".

    Log readability only — never apply before persisting. A record that really
    spent $0 must still serialize `cost_usd: 0.0`, or a spend report counts
    unknown spend as free.
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
