from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import FindByLexicalTraitsExecutor
from .external import FindByLexicalTraitsInput, FindByLexicalTraitsOutput
from .labels import FindLexicalTraitsNodeTypeEnum
from .schemas import FindByLexicalTraitsArgs, FindByLexicalTraitsRetrieval

SPEC = NodeSpec(
    node_type=FindLexicalTraitsNodeTypeEnum.REQUEST.value,
    tier=NodeTier.RETRIEVAL,
    request=FindByLexicalTraitsRetrieval,
    input=FindByLexicalTraitsInput,
    output=FindByLexicalTraitsOutput,
    executor=FindByLexicalTraitsExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "FindByLexicalTraitsArgs",
    "FindByLexicalTraitsExecutor",
    "FindByLexicalTraitsInput",
    "FindByLexicalTraitsOutput",
    "FindByLexicalTraitsRetrieval",
    "FindLexicalTraitsNodeTypeEnum",
]
