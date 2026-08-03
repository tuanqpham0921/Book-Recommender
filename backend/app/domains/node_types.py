from typing import Union
from enum import Enum
from app.domains.books.node_types import BookNodeTypeEnum


class UnknownNodeTypeEnum(Enum):
    UNKNOWN = "unknown"

NodeTypeEnum = Union[
    BookNodeTypeEnum, 
    UnknownNodeTypeEnum,
]