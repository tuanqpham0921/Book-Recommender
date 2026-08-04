from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindByTitleExecutor
from .labels import FindTitleNodeTypeEnum
from .schemas import FindByTitleOutput, FindByTitleRetrieval

SPEC = NodeSpec(
    node_type=FindTitleNodeTypeEnum.REQUEST.value,
    tier=NodeTier.RETRIEVAL,
    request=FindByTitleRetrieval,
    output=FindByTitleOutput,
    executor=FindByTitleExecutor,
)

__all__ = [
    "SPEC",
    "FindByTitleExecutor",
    "FindTitleNodeTypeEnum",
    "FindByTitleOutput",
    "FindByTitleRetrieval",
]
