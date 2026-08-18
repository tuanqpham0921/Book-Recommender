from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FilterRetrievalExecutor
from .labels import FilterRetrievalNodeTypeEnum
from .schemas import FilterRetrieval
from .external import FilterRetrievalInput, FilterRetrievalOutput

SPEC = NodeSpec(
    node_type=FilterRetrievalNodeTypeEnum.REQUEST.value,
    tier=NodeTier.COMBINE,
    request=FilterRetrieval,
    input=FilterRetrievalInput,
    output=FilterRetrievalOutput,
    executor=FilterRetrievalExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FilterRetrievalExecutor",
    "FilterRetrievalNodeTypeEnum",
    "FilterRetrievalInput",
    "FilterRetrievalOutput",
    "FilterRetrieval",
]
