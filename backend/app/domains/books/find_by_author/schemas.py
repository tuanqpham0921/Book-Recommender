from app.domains.base_request import BaseRequest

from pydantic import BaseModel, Field
from typing import Literal
from .labels import FindAuthorNodeTypeEnum


class FindByAuthorRetrieval(BaseRequest):
    """Purpose: Retrieve the books written by one named author.

    Args:
        author: The single author whose books to retrieve.

    Returns: BookRetrievalOutput — that author's catalog.

    depends_on: None — this node queries the database directly.

    Use when: one author is the subject of the search — "books by Ursula K. Le
    Guin", "what else has Brandon Sanderson written".

    Do not use: for taste-based suggestions. For books two or more authors
    wrote *together*, use Retrieve_by_CoAuthors instead. When a title and an
    author are named together ("Dune by Frank Herbert", "did Frank Herbert
    write Dune"), this node is right but not on its own — Retrieve_by_Title
    carries the title, this node carries the author, and Combine_Intersect
    ANDs them, so the pairing is checked against the data rather than taken on
    trust.

    Constraints: exactly one author per node — several authors mean one node
    per author ("books by Austen and by Coelho" → two nodes), because each node
    returns one author's catalog. This node searches on the author alone and
    takes no title, genre or metadata argument.

    Example queries:
        - "books by Ursula K. Le Guin"
        - "what else has Brandon Sanderson written"
        - "show me some Agatha Christie"
    """

    node_type: Literal[FindAuthorNodeTypeEnum.REQUEST] = FindAuthorNodeTypeEnum.REQUEST


class FindByAuthorArgs(BaseModel):
    """Search the catalog for the author named in the query."""

    author: str = Field(..., json_schema_extra={"example": "Ursula K. Le Guin"})
