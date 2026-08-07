"""Shared result payloads for the book domain — the contract downstream nodes
(e.g. Analyze_Recommend reading a dependency's result) and eval/review tooling
see. `Book` is the one book model: every books-table column except the
embedding. Narrowing happens where a consumer needs it — a prompt renderer
picking the fields it wants, or `model_dump(include=...)` — never by declaring
a second, smaller model. See `Book`'s docstring for why.

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

from pydantic import BaseModel, ConfigDict, Field

from app.domains.node_executor import NodeWorkflowOutput
from db.stores import DeferredBookQuery

class Book(BaseModel):
    """One book, as everything above the database layer sees it: every column
    of the `books` table except the embedding, matching what
    `BookModel.to_dict()` (db/schema/models.py) hands back.

    **The embedding's absence is load-bearing, not an oversight.** These models
    are serialized into `chat_runs` JSONB by `record_chat_run`; a 1536-float
    vector per book would bloat every run record for something no reader of it
    can use. Do not add the field "for completeness" — if a caller needs
    vectors, it should go to the store.

    There is deliberately no narrower book model. An earlier `ReferenceBook`
    tried to keep presentation fields away from the LLM prompts, but the
    prompt-facing renderers already select fields by hand
    (analyze_recommend/analyze_references.py, generate_response.py), so the
    type was never the thing enforcing it — it was a second field list free to
    drift from this one, and it did. Narrow at the point of use instead.

    Field names are a **persisted contract**: they land in `chat_runs.tasks`
    and are read back by the review page and the eval reports, so a rename
    silently breaks readers against older rows. Every field needs a default
    except the two that identify a book, because `Workflow.__init__` builds
    output envelopes before there is anything to put in them.
    """

    isbn13: str
    title: str
    isbn10: str | None = None
    authors: str | None = None
    categories: str | None = None
    genre: str | None = None
    published_year: int | None = None
    num_pages: int | None = None
    average_rating: float | None = None
    ratings_count: int | None = None
    is_children: bool | None = None
    description: str | None = None
    thumbnail: str | None = None
    title_and_subtiles: str | None = None

    # Not a column: `BookStore.search_by_embedding` attaches it to the row, and
    # it is the only record of how close a recommendation actually was — kept
    # so "why these books" stays answerable from the run log. None on a book
    # that arrived by any other route.
    similarity_score: float | None = None


class BookRetrievalOutput(NodeWorkflowOutput):
    """A list of books, as produced by any retrieval or combine node. An empty
    `books` is a real answer — it means nothing matched, not that the node
    failed.

    Counts-first, per docs/design/execution-pipeline-v1.md: a retrieval node
    fills in `num_books` and `query` and puts at most a small sample of rows in
    `books` — `BookNodeExecutor.preflight` (books/executor.py) does all of that
    in one round trip. Only the last node in a plan runs `query` for the set.

    **`num_books` vs `len(books)` is therefore the load-bearing comparison**:
    `num_books` is the size of the match, `len(books)` is the size of the fetch.
    When they differ, `books` is a handful of rows shown under the count in the
    UI so "1,240 books" comes with evidence of what they look like — ranked for
    recognizability rather than correctness, and not the node's answer. Anything
    downstream that needs the real set has to go through `query` instead of
    reading those rows.

    `query` is `exclude=True` on purpose: `to_serializable` (common/utils/
    format.py) skips excluded fields but does walk private attrs, so a
    SQLAlchemy statement stashed anywhere else on this model reaches the JSONB
    insert in `record_chat_run` and breaks it. `query_sql` is the persisted,
    readable stand-in.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    builds the envelope by calling `output_type()` with no arguments, before
    the executor has anything to put in it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    books: list[Book] = Field(
        default_factory=list,
        description="rows actually fetched — the whole match, or a sample of it",
    )
    num_books: int = 0
    query_sql: str | None = None
    query: DeferredBookQuery | None = Field(default=None, exclude=True)

    def to_summary(self, preview_num = 3) -> dict[str, Any]:
        return {
            "num_books": self.num_books,
            "num_fetched": len(self.books),
            "preview": [book.title for book in self.books[:preview_num]],
        }


class BookRecommendationOutput(BookRetrievalOutput):
    """Books that were *chosen* rather than merely matched. Structurally a
    retrieval output, so anything that consumes books consumes this too."""
