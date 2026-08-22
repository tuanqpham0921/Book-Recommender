from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindSimilarBooksExecutor
from .labels import SimilarBooksNodeTypeEnum
from .schemas import SimilarBooksSearch
from .external import SimilarBooksInput, SimilarBooksOutput

SPEC = NodeSpec(
    node_type=SimilarBooksNodeTypeEnum.REQUEST.value,
    tier=NodeTier.ANALYZE,
    request=SimilarBooksSearch,
    input=SimilarBooksInput,
    output=SimilarBooksOutput,
    executor=FindSimilarBooksExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FindSimilarBooksExecutor",
    "SimilarBooksNodeTypeEnum",
    "SimilarBooksInput",
    "SimilarBooksOutput",
    "SimilarBooksSearch",
]
