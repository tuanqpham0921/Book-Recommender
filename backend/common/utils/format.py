import traceback
from typing import Any
from pydantic import BaseModel

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any
from pathlib import Path

def format_exception(error: BaseException) -> dict[str, Any]:
    """Return a JSON-friendly traceback payload for operation logs."""
    frames = traceback.extract_tb(error.__traceback__)
    formatted_frames = [
        {
            "file": frame.filename,
            "line": frame.lineno,
            "function": frame.name,
            "code": frame.line,
        }
        for frame in frames
    ]

    origin = formatted_frames[-1] if formatted_frames else None

    return {
        "type": type(error).__name__,
        "message": str(error),
        "origin": origin,
        "frames": formatted_frames,
        "traceback": traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
        ),
    }
    
def to_jsonable(value: Any) -> Any:
    """Convert app/Pydantic objects into readable JSON-compatible values."""
    if isinstance(value, type):
        return value.__name__

    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
        # include private attributes
        if value.__pydantic_private__:
            data.update(value.__pydantic_private__)

        return data

    if is_dataclass(value):
        return {
            field.name: to_jsonable(getattr(value, field.name))
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
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]

    return value
    
def remove_json_empty_values(value: Any) -> Any:
    """Drop None, empty strings, and empty collections from summary payloads."""
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json", exclude_none=True)
        return remove_json_empty_values(data)
        
    if isinstance(value, dict):
        cleaned = {key: remove_json_empty_values(item) for key, item in value.items()}
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != "" and item != [] and item != {}
        }

    if isinstance(value, list):
        cleaned = [remove_json_empty_values(item) for item in value]
        return [
            item
            for item in cleaned
            if item is not None and item != "" and item != [] and item != {}
        ]

    return value