# Common utility function for handling json
import json
import logging
from pathlib import Path
from typing import Any

from airglider import remove_empty_values, to_serializable
from config import FilesLocationConstants

logger = logging.getLogger(__name__)


def print_json(data: Any, name: str | None = None, indent: int = 2, color: bool = True):
    """Pretty-print JSON data with an optional label."""
    serializable = to_serializable(data)
    output = json.dumps(serializable, indent=indent, ensure_ascii=False)

    if name:
        print(f"\n********** {name} **************")

    if color:
        try:
            from pygments import highlight, lexers, formatters

            output = highlight(
                output, lexers.JsonLexer(), formatters.TerminalFormatter()
            )
        except ImportError:
            pass

    print(output)
    if name:
        print("******************************\n")


def save_file(
    data,
    file_name: str = "log",
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
    remove_empty: bool = True,
):
    """Save Json to file"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    jsonable = to_serializable(data)
    if remove_empty:
        jsonable = remove_empty_values(jsonable)

    json_str = json.dumps(jsonable, indent=2, default=str)

    file_name = file_name.removesuffix(".json")
    filepath = path / f"{file_name}.json"
    with open(filepath, "w") as f:
        f.write(json_str)

    logger.info(f"📋 log written to {filepath}")


def save_text(
    text: str,
    file_name: str = "log.txt",
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
):
    """Save a raw string to a text file, with real newlines (no JSON escaping).

    Unlike save_file, this writes the string verbatim and keeps whatever
    extension file_name carries (defaulting to .txt)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    if "." not in Path(file_name).name:
        file_name = f"{file_name}.txt"
    filepath = path / file_name
    filepath.write_text(text)

    logger.info(f"📋 text written to {filepath}")


def load_json(
    file_name: str,
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
) -> dict | list | None:
    """load json from file"""
    path = Path(path)
    file_name = file_name.removesuffix(".json")
    filepath = path / f"{file_name}.json"

    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return None

    with open(filepath) as f:
        data = json.load(f)

    logger.info(f"📋 loaded from {filepath}")
    return data
