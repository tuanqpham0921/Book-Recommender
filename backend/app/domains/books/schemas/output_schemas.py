"""Structured result payloads for book retrieval nodes — the contract
downstream nodes (e.g. Analyze_Recommend reading a dependency's result) and
eval/review tooling see. Deliberately excludes description/thumbnail/
embedding: those are presentation/internal fields, not reasoning inputs.
Full book-card data (including thumbnail) is streamed to the UI separately
via SSEStream.send_book_card and doesn't go through these models.
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


class FindByTitleOutput(BaseModel):
    title: str
    books: list[BookSummary]


class FindByISBN13Output(BaseModel):
    isbn13: str
    book: BookSummary | None = None


class FindByAuthorOutput(BaseModel):
    authors: list[str]
    books: list[BookSummary]


class FindByGenreOutput(BaseModel):
    genre: str
    books: list[BookSummary]
