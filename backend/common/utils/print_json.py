import json

from enum import Enum
from typing import Any
from pydantic import BaseModel
from common.utils.format import to_jsonable


def print_json(data: Any, name: str | None = None, indent: int = 2, color: bool = True):
    """Pretty-print JSON data with an optional label."""
    serializable = to_jsonable(data)
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
        
