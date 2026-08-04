from app.domains.base_request import BaseRequest
from app.domains.books.schemas import BookRetrievalOutput
from pydantic import Field
from typing import Literal
from .labels import FindTitleNodeTypeEnum

class FindByTitleRetrieval(BaseRequest):
    """Purpose: Retrieve the books whose titles most closely match the one given.

    Args:
        title: Book title to search for.

    Returns: BookRetrievalOutput — the candidate matches, best first.

    depends_on: None — this node queries the database directly.

    Use when: a specific title is named — "find Dune", "do you have The Great
    Gatsby".

    Do not use: when the author is the actual subject of the search ("books by
    Frank Herbert"), or when no specific title is named.

    Constraints: one title per node — for multiple named titles, emit one node
    per title. This node searches on the title alone and takes no author
    argument. When a title and an author are named together ("Dune by Frank
    Herbert"), or the question is whether a given author wrote a given title
    ("did Frank Herbert write Dune"), the author is a second retrieval
    dimension: emit Retrieve_by_Author alongside this node and AND them with
    Combine_Intersect. That checks the pairing against the data instead of
    taking it on trust, and an empty intersection is the real answer to "did X
    write Y?".

    Example queries:
        - "find Dune"
        - "do you have The Great Gatsby"
    """

    node_type: Literal[FindTitleNodeTypeEnum.REQUEST] = FindTitleNodeTypeEnum.REQUEST
    title: str = Field(..., json_schema_extra={"example": "Dune"})

class FindByTitleOutput(BookRetrievalOutput):
    """`title` is what was searched for; `books` are the candidate matches,
    best first. An empty `books` means the catalog has no such title."""

    title: str = ""

