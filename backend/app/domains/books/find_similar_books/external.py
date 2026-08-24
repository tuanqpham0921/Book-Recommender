from pydantic import BaseModel, Field
from typing import Any

from app.domains.books.external import BookAnchorOutput, BookCandidateOutput
from app.domains.books.schemas import Book
from app.domains.node_input import NodeInput


class SimilarBooksInput(NodeInput):
    """The books to be similar *to* — named ones only.

    `anchors` is required, and both halves of the requirement are the node's
    contract. **The type**: only a book the user *named* can be folded into a
    description of what to look for next, so `list[BookAnchorOutput]` structurally
    refuses a bibliography or a subject search — `build_input` fills by
    `isinstance`, and a plan that tries is skipped at dispatch naming this field
    rather than dying inside the node. **The `min_length`**: `build_input` fills a
    `list[X]` with every match and an empty list is still a *filled* field, so a
    bare `...` would never fire.

    There is no fallback to fall back to. A similarity search with nothing to be
    similar to is a different question — one no registered node answers today.

    No `documents` field: `AnalyzeBooksOutput` is a reserved name with no class,
    and a field can only select by type against a type that exists.
    """

    anchors: list[BookAnchorOutput] = Field(..., min_length=1)


class ScoreStats(BaseModel):
    """How close the pool actually sits, as cosine similarity.

    The pool is truncated to `CANDIDATE_POOL_SIZE`, so `num_books` reports that
    number far more often than it reports a match size — these are what say
    whether the pool found anything worth keeping. A `min` resting on
    `BookConstraints.MIN_SIMILARITY` means the floor never bound and the LIMIT
    chose the whole pool; a `min` well above it means the floor did the cutting
    and the pool is smaller than its ceiling.

    It is also the record `Book.similarity_score` used to keep. Per-book, that
    field only survived as far as the browser, where `BookOut` dropped it; the
    spread reaches `chat_runs` and is what "why these books" is answered from.
    """

    count: int
    min: float
    max: float
    avg: float


class SimilarBooksOutput(BookCandidateOutput):
    """How many books sit nearest the anchor, and the query that reaches them.

    A **candidate** set, and on the candidate side for the same reason every
    other one is: these books match a *description* — the one this node
    synthesized — rather than a reference the user gave. So the pool can never
    be fed back in as an anchor to another similarity search, and a later node
    that re-ranks or picks from it declares `list[BookCandidateOutput]`.

    Shaped like every other retrieval — a count and a query, no rows — which it
    was not until 2026-08-24. `embedding_search_stmt` carries an ORDER BY and a
    LIMIT, and this node used to hand on 50 fetched rows because
    `DeferredBookQuery` forbids both by invariant. It now takes that invariant's
    one documented exception instead, because the rows cost more than the
    exception does: with a query, `Filter_Retrieval` narrows the pool in SQL
    and `score` carries cosine order through the narrowing, so a bound on a
    similarity ask is expressible without this node parsing one.

    Counting, narrowing and materializing `query` are all safe. **Composing it
    is not** — the LIMIT applies before the union or intersect, so it changes
    which books qualify, and `compose()` then drops the `score` that chose
    them. Nothing enforces that; see `DeferredBookQuery`. `score` is what
    describes this output, since `num_books` mostly reports the pool size.

    `references` and `search_text` are kept because "why these books" is only
    answerable against what was pointed at and what was embedded. `search_text`
    is the synthesized ideal-book description — what the embedding actually saw
    — not anything the user typed.
    """

    references: list[Book] = Field(default_factory=list)
    search_text: str | None = None
    score: ScoreStats | None = Field(
        default=None,
        description="the pool's cosine spread — None when nothing cleared the floor",
    )

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the pool, not the books in it — none are carried now.

        A summary is read at a glance, and the two numbers worth glancing at
        are how big the pool is and how close it sits.
        """
        return {
            "num_books": self.num_books,
            "num_references": len(self.references),
            "score": self.score.model_dump() if self.score else None,
        }
