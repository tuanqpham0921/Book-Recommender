from typing import Literal

from pydantic import BaseModel, model_validator

class SessionOut(BaseModel):
    id: str
    created_at: str

class ChatIn(BaseModel):
    message: str

FeedbackCategory = Literal["Content", "Recommendation", "Planner", "Time", "UI/UX", "Other"]

class ReviewCommentIn(BaseModel):
    """One observation inside a review."""

    title: FeedbackCategory | None = None
    message: str
    positive: bool = False

class ReviewIn(BaseModel):
    """One review of a chat run, upserted whole per (chat_id, session_id):
    the reviewer's overall like/dislike plus their comment list. session_id
    is the reviewing session, which may differ from the session that
    produced the run; re-submitting from the same session replaces the
    previous version."""

    chat_id: str
    session_id: str
    liked: bool | None = None
    comments: list[ReviewCommentIn] = []

    @model_validator(mode="after")
    def _has_substance(self):
        if self.liked is None and not self.comments:
            raise ValueError(
                "a review needs an overall reaction or at least one comment"
            )
        return self

class BookOut(BaseModel):
    """One book as the chat client receives it, in a `book_card` SSE event.

    The wire contract for a book, and the only place the frontend's field
    names are pinned on this side. `Book` (app/domains/books/schemas.py) is the
    internal model and carries every catalog column; this is the subset the UI
    renders — `BookCard`, `BookCardDetailed`, `BookCover` and `BookDetailModal`
    between them read exactly these fields and nothing else.

    Unlike the prompt-facing renderers, which pick their fields inline, the
    narrowing here is a *type* on purpose: serialization is the boundary, so a
    field added to `Book` reaches the browser unless something stops it, and
    this class is that something. `similarity_score` is the standing example —
    internal ranking evidence, kept in the run log, never shipped to a client.

    Adding or renaming a field here is a frontend change: the components read
    these names straight off the event payload, so a rename breaks rendering
    silently, with no error raised on either side.
    """

    isbn13: str
    title: str
    authors: str | None = None
    categories: str | None = None
    published_year: int | None = None
    num_pages: int | None = None
    average_rating: float | None = None
    description: str | None = None
    thumbnail: str | None = None


class HealthStatus(BaseModel):
    """Health check response model."""

    orchestrator: bool = False
    sqlalchemy_engine: bool = False
    message: str = "Service status"