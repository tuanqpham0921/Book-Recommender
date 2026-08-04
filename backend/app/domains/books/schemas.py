"""Shared result payloads for the book domain — the contract downstream nodes
(e.g. Analyze_Recommend reading a dependency's result) and eval/review tooling
see. Deliberately excludes description/thumbnail/embedding: those are
presentation/internal fields, not reasoning inputs. Full book-card data
(including thumbnail) is streamed to the UI separately via
SSEStream.send_book_card and doesn't go through these models.

## The output-shape vocabulary

Node docstrings name what they return and what they may depend on using four
shape names, so the planner can tell which nodes can legally feed which:

- `BookRetrievalOutput` — a list of books. Every retrieval node and the whole
  combine tier. The only shape a node that "depends on books" can consume.
- `BookRecommendationOutput` — a list of books that were *chosen*, from
  `Analyze_Recommend`. Consumable anywhere books are.
- `AnalyzeBooksOutput` — a written report about books (compare, summarize,
  themes, reading order/level/time/plan). Names books without being a book
  list: a report never adds a book, so nothing may treat it as a retrieval.
- `ActionConfirmationOutput` — a record of a write (shelf actions, feedback).

The first two are real classes here, and a node's own output subclasses the one
it claims in its docstring — so `Returns:` is checkable rather than a promise.
The last two are **reserved names with no class yet**: no node in the current
set produces a report or performs a write. Docstrings that reference them
describe an intended contract, not something the code enforces. Add the class
alongside the first node that produces the shape. See
docs/design/node-taxonomy-v1.md.

Node-specific fields (which title was searched for, which genre) live on the
slice's own output in `app/domains/books/<node>/schemas.py`, which subclasses
the shape it returns.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.domains.node_executor import NodeWorkflowOutput


class BookSummary(BaseModel):
    isbn13: str
    title: str
    authors: str | None = None
    categories: str | None = None
    genre: str | None = None
    published_year: int | None = None
    num_pages: int | None = None
    average_rating: float | None = None
    ratings_count: int | None = None
    is_children: bool | None = None


class BookRetrievalOutput(NodeWorkflowOutput):
    """A list of books, as produced by any retrieval or combine node. An empty
    `books` is a real answer — it means nothing matched, not that the node
    failed.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    builds the envelope by calling `output_type()` with no arguments, before
    the executor has anything to put in it.
    """

    books: list[BookSummary] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {"num_books": len(self.books)}


class BookRecommendationOutput(BookRetrievalOutput):
    """Books that were *chosen* rather than merely matched. Structurally a
    retrieval output, so anything that consumes books consumes this too."""
