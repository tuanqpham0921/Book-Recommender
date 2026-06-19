from app.domains.books.types import NodeTypeEnum as BookNodeTypeEnum
from app.domains.users.types import NodeTypeEnum as UserNodeTypeEnum
from app.domains.project.types import NodeTypeEnum as ProjectNodeTypeEnum
from typing import Union

NodeTypeEnum = Union[BookNodeTypeEnum, UserNodeTypeEnum, ProjectNodeTypeEnum]
