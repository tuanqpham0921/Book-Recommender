import traceback
from typing import Any

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