from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import CombineIntersectExecutor
from .labels import CombineIntersectNodeTypeEnum
from .schemas import CombineIntersect
from .external import CombineIntersectInput, CombineIntersectOutput

SPEC = NodeSpec(
    node_type=CombineIntersectNodeTypeEnum.REQUEST.value,
    tier=NodeTier.COMBINE,
    request=CombineIntersect,
    input=CombineIntersectInput,
    output=CombineIntersectOutput,
    executor=CombineIntersectExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "CombineIntersectExecutor",
    "CombineIntersectNodeTypeEnum",
    "CombineIntersectInput",
    "CombineIntersectOutput",
    "CombineIntersect",
]
