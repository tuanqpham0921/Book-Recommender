from typing import Union

from app.domains.books.types import NodeTypeEnum as BookNodeTypeEnum
from app.domains.project.types import NodeTypeEnum as ProjectNodeTypeEnum
from app.domains.users.types import NodeTypeEnum as UserNodeTypeEnum

NodeTypeEnum = Union[BookNodeTypeEnum, UserNodeTypeEnum, ProjectNodeTypeEnum]
