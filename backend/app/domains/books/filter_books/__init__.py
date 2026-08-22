from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FilterRetrievalExecutor, describe_bounds
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
    # a pure renderer over `BookMetadataFilter`, not part of the node:
    # `find_by_numeric_traits` parses its own bounds and needs the same
    # sentence. Its only caller since the similarity slice stopped parsing any.
    "describe_bounds",
    "FilterRetrievalNodeTypeEnum",
    "FilterRetrievalInput",
    "FilterRetrievalOutput",
    "FilterRetrieval",
]
