import json
import logging
from pathlib import Path
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from config import FilesLocationConstants

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    """Convert app/Pydantic objects into readable JSON-compatible values."""
    if isinstance(value, BaseModel):
        print(f"!!!!!!!!Value: {value.model_dump(mode="json")}")
        return value.model_dump(mode="json")

    if is_dataclass(value):
        return {
            field.name: _to_jsonable(getattr(value, field.name))
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
        return {str(key): _to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]

    return value


def save_file(
    data,
    file_name: str = "log",
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    json_str = json.dumps(_to_jsonable(data), indent=2, default=str)
    filepath = path / f"{file_name}.json"
    with open(filepath, "w") as f:
        f.write(json_str)
    
    if logger:
        logger.info(f"📋 log written to {filepath}")
    else:
        print(f"📋 log written to {filepath}")