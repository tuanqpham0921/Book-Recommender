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
