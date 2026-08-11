"""Serialization and identity helpers for record trees.

Self-contained on purpose: airglider imports nothing from the host app, so
these live here rather than being borrowed from a shared `utils` package. The
host is free to re-export them (see `common/utils/`) instead of keeping a
second copy.
"""

import inspect
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


def bind_call_args(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """A call's arguments keyed by their parameter names.

    `f(some_input)` and `f(node_input=some_input)` are the same call, so a
    record that stored positional arguments by index would key the same thing
    two ways. Binding against the signature gives one name per value.

    A leading `self`/`cls` is dropped: for a decorated *method* the receiver is
    args[0], and recording the whole client or workflow object is both noise
    and, for a non-serializable one, a hazard.

    Returns `{}` rather than raising when the arguments don't fit the
    signature — the call itself is about to raise a much better error, and
    bookkeeping must not pre-empt it.
    """
    try:
        parameters = inspect.signature(func).parameters
        bound = inspect.signature(func).bind(*args, **kwargs)
    except (TypeError, ValueError):
        return {}

    # deliberately no apply_defaults(): the record says what the caller passed,
    # and filling in every default turns a one-key call into a wall of them
    arguments = dict(bound.arguments)
    first = next(iter(parameters), None)
    if first in ("self", "cls"):
        arguments.pop(first, None)
    return arguments


def to_record_input(value: Any) -> Any:
    """`to_serializable`, except anything that can summarize itself does.

    Written for `OperationResult.input`, where the same payload is often
    already recorded in full somewhere else: a node's input carries the output
    of the node before it, whose own envelope holds every field of it. Dumping
    it again would store the same rows once per dependent, and the trace grows
    with the square of the plan's depth rather than its size.

    `to_summary()` is the same opt-in hook `OperationResult.to_summary` already
    honours for payloads, so a type says how it wants to appear in a record
    once, in one place. Everything without one — the query string, the parsed
    arguments — is serialized whole, which is the point: those are the small,
    unique parts of the call.

    **The result is always JSON-encodable.** Unlike `to_serializable`, which
    passes an unrecognized value through untouched, anything left over here is
    reduced to its type name. Arguments are not payloads a caller chose to
    record — they are whatever the function happens to take, and half the
    `@task` call sites in a typical host take a live handle (a DB session, a
    client). One of those reaching the envelope makes the whole tree
    unserializable, at the JSONB insert, long after the call it came from.
    """
    to_summary = getattr(value, "to_summary", None)
    if callable(to_summary):
        return to_summary()

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

    # a live handle, or anything else with no serializable form. Its type is
    # the whole useful content — "it was called with a session" — and is what
    # keeps the rest of the record intact.
    return f"<{type(value).__name__}>"


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
    (`ok: False`, a genuine count of 0 are real answers, not absence — see
    test_preserves_zero_and_false), so a generic "drop zero scalars" rule
    would be wrong there. `token_usage` is the one place an all-zero shape
    really does mean "nothing to report" — a step that made no LLM call — so
    it gets a name-scoped rule instead of a general one.

    Log readability only. Never apply this before persisting a record: an
    envelope that genuinely spent $0 must still serialize `cost_usd: 0.0`
    there, not vanish into the same shape as a record written before cost
    tracking existed, with no `token_usage` key at all. That distinction is
    what lets a spend report average real zeros without quietly counting
    unknown spend as free. Run this only after `remove_empty_values`, on the
    copy written to a local file.
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
