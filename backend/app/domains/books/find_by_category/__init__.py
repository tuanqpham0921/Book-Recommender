from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindByCategoryExecutor
from .external import FindByCategoryInput, FindByCategoryOutput
from .labels import FindCategoryNodeTypeEnum
from .schemas import FindByCategoryArgs, FindByCategoryRetrieval

SPEC = NodeSpec(
    node_type=FindCategoryNodeTypeEnum.REQUEST.value,
    tier=NodeTier.RETRIEVAL,
    request=FindByCategoryRetrieval,
    input=FindByCategoryInput,
    output=FindByCategoryOutput,
    executor=FindByCategoryExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FindByCategoryArgs",
    "FindByCategoryExecutor",
    "FindByCategoryInput",
    "FindByCategoryOutput",
    "FindByCategoryRetrieval",
    "FindCategoryNodeTypeEnum",
]
