from typing import Union
from enum import Enum
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.project.node_types import ProjectNodeTypeEnum
from app.domains.users.node_types import UserNodeTypeEnum

class UnknownNodeTypeEnum(Enum):
    UNKNOWN = "unknown"

NodeTypeEnum = Union[
    BookNodeTypeEnum, 
    UserNodeTypeEnum,
    ProjectNodeTypeEnum,
    UnknownNodeTypeEnum,
]
