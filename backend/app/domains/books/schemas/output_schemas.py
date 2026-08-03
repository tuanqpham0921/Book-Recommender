"""Structured result payloads for book retrieval nodes — the contract
downstream nodes (e.g. Analyze_Recommend reading a dependency's result) and
eval/review tooling see. Deliberately excludes description/thumbnail/
embedding: those are presentation/internal fields, not reasoning inputs.
Full book-card data (including thumbnail) is streamed to the UI separately
via SSEStream.send_book_card and doesn't go through these models.

## The output-shape vocabulary (added 2026-07-28)

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

Shapes outside the vocabulary are spelled out per node (`AuthorInfoOutput`,
`ReadingStatsOutput`, `UserInfoOutput`, …); they are about people, stats, or
accounts, not books, and nothing that depends on books can consume them.

**These four names are planner-facing only — they are not classes here.** This
module still defines one concrete Output class per node (`FindByTitleOutput`,
`FindByGenreOutput`, …), all structurally `{what_was_searched, books}`, and
there is no class at all for the recommendation, analyze, or confirmation
shapes. Collapsing the per-node classes into a real `BookRetrievalOutput` and
adding the missing three would make the docstrings and the code agree; until
then, the docstrings describe an intended contract that the executors do not
yet enforce. See docs/design/node-taxonomy-v1.md.
"""

from pydantic import BaseModel


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

class RecommendationOutput(BaseModel):
    books: list[BookSummary]

class FindByTitleOutput(BaseModel):
    title: str
    books: list[BookSummary]


class FindByISBN13Output(BaseModel):
    isbn13: str
    book: BookSummary | None = None


class FindByAuthorOutput(BaseModel):
    author: str
    books: list[BookSummary]


class FindByCoAuthorsOutput(BaseModel):
    """`authors` are the names that were searched for jointly; every book in
    `books` is credited to all of them. An empty `books` is a real answer here
    — it means the named authors never collaborated."""

    authors: list[str]
    books: list[BookSummary]


class FindByGenreOutput(BaseModel):
    genre: str
    books: list[BookSummary]


class RandomBookOutput(BaseModel):
    """Arbitrarily chosen books — as many as the request's `limit` asked for,
    fewer if the catalog (or the supplied filters) could not supply that many.
    An empty `books` is a real answer, not an error."""

    books: list[BookSummary]
