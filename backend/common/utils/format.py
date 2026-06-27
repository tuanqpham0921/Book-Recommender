import traceback
from typing import Any
from pydantic import BaseModel

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