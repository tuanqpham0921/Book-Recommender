import json
import logging
from pathlib import Path

from config import FilesLocationConstants

logger = logging.getLogger(__name__)


import json

from typing import Any
from common.utils.format import to_serializable


def print_json(data: Any, name: str | None = None, indent: int = 2, color: bool = True):
    """Pretty-print JSON data with an optional label."""
    serializable = to_serializable(data)
    output = json.dumps(serializable, indent=indent, ensure_ascii=False)

    if name:
        print(f"\n********** {name} **************")

    if color:
        try:
            from pygments import highlight, lexers, formatters
            output = highlight(output, lexers.JsonLexer(), formatters.TerminalFormatter())
        except ImportError:
            pass

    print(output)
    if name:
        print("******************************\n")
        



def load_json(
    file_name: str,
    path: Path | str = FilesLocationConstants.EXPORT_DIR,
) -> dict | list | None:
    path = Path(path)
    file_name = file_name.rstrip(".json")
    filepath = path / f"{file_name}.json"

    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return None

    with open(filepath) as f:
        data = json.load(f)

    logger.info(f"📋 loaded from {filepath}")
    return data

