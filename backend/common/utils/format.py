from typing import Any
from pydantic import BaseModel

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any
from pathlib import Path


def to_serializable(value: Any) -> Any:
    """Convert app/Pydantic objects into readable JSON-compatible values."""
    if isinstance(value, type):
        return value.__name__

    if isinstance(value, BaseModel):
        data = value.model_dump(exclude_none=True)
        # include private attributes
        if value.__pydantic_private__:
            data.update(value.__pydantic_private__)

        return to_serializable(data)

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
    """Drop None, empty strings, and empty collections from summary payloads."""
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json", exclude_none=True)
        return remove_empty_values(data)

    if isinstance(value, dict):
        cleaned = {key: remove_empty_values(item) for key, item in value.items()}
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != "" and item != [] and item != {}
        }

    if isinstance(value, list):
        cleaned = [remove_empty_values(item) for item in value]
        return [
            item
            for item in cleaned
            if item is not None and item != "" and item != [] and item != {}
        ]

    return value
