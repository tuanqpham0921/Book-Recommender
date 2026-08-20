from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindByAuthorExecutor
from .labels import FindAuthorNodeTypeEnum
from .schemas import FindByAuthorRetrieval
from .external import FindByAuthorInput, FindByAuthorOutput

SPEC = NodeSpec(
    node_type=FindAuthorNodeTypeEnum.REQUEST.value,
    tier=NodeTier.RETRIEVAL,
    request=FindByAuthorRetrieval,
    input=FindByAuthorInput,
    output=FindByAuthorOutput,
    executor=FindByAuthorExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FindByAuthorExecutor",
    "FindAuthorNodeTypeEnum",
    "FindByAuthorInput",
    "FindByAuthorOutput",
    "FindByAuthorRetrieval",
]
