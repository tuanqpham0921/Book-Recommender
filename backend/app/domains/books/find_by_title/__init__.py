from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindByTitleExecutor
from .labels import FindTitleNodeTypeEnum
from .schemas import FindByTitleRetrieval
from .external import FindByTitleInput, FindByTitleOutput

SPEC = NodeSpec(
    node_type=FindTitleNodeTypeEnum.REQUEST.value,
    tier=NodeTier.RETRIEVAL,
    request=FindByTitleRetrieval,
    input=FindByTitleInput,
    output=FindByTitleOutput,
    executor=FindByTitleExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FindByTitleExecutor",
    "FindTitleNodeTypeEnum",
    "FindByTitleInput",
    "FindByTitleOutput",
    "FindByTitleRetrieval",
]
