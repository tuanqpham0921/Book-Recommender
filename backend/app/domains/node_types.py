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

# # for extended node types
# # comment out or keep when you want to extend
# from playground.app_mock.extended_node_types import ExtendedBookNodeTypeEnum
# NodeTypeEnum = Union[
#     NodeTypeEnum,
#     ExtendedBookNodeTypeEnum
# ]