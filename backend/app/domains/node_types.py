from typing import Union

from app.domains.books.node_types import NodeTypeEnum as BookNodeTypeEnum
from app.domains.project.node_types import NodeTypeEnum as ProjectNodeTypeEnum
from app.domains.users.node_types import NodeTypeEnum as UserNodeTypeEnum

NodeTypeEnum = Union[BookNodeTypeEnum, UserNodeTypeEnum, ProjectNodeTypeEnum]
