from app.domains.books.types import NodeType as BookNodeType
from app.domains.users.types import NodeType as UserNodeType
from app.domains.project.types import NodeType as ProjectNodeType
from typing import Union

NodeType = Union[BookNodeType, UserNodeType, ProjectNodeType]