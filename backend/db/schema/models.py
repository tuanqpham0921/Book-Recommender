# SQLAlchemy models (shared by stores / DB layers)
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, DateTime, Integer, String, Float, Text, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

from config import settings

Base = declarative_base()

# TODO: this is an ORM file, we should avoid confusion with dataclasses
class BookModel(Base):
    """SQLAlchemy model for books table."""

    __tablename__ = "books"

    # Book identifiers
    isbn13 = Column(String(13), primary_key=True, index=True)
    isbn10 = Column(String(10), nullable=True, index=True)

    # Basic book information
    title = Column(String(500), nullable=False, index=True)
    authors = Column(String, nullable=True, index=True)
    categories = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    # description embedding
    embedding = Column(Vector(settings.openai.EMBEDDING_DIMENSIONS), nullable=True)

    # Publication details
    published_year = Column(Integer, nullable=True, index=True)

    # Physical properties
    num_pages = Column(Integer, nullable=True)

    # Ratings and reviews
    average_rating = Column(Float, nullable=True, index=True)

    # Content flags
    is_children = Column(Boolean, nullable=True, default=False)

    # Search and recommendation fields
    genre = Column(String(100), nullable=True, index=True)

    thumbnail = Column(String, nullable=True)
    # large_thumbnail = Column(String, nullable=True)

    ratings_count = Column(Integer, nullable=True)

    # Misc presentation fields
    title_and_subtiles = Column(Text, nullable=True)

    def __repr__(self):
        return f"<BookModel(isbn13='{self.isbn13}', title='{self.title}')>"

    def to_dict(self, *, include_embedding: bool = False) -> dict:
        """Convert model to dictionary (table columns only)."""
        columns = BookModel.__table__.columns
        if not include_embedding:
            columns = [c for c in columns if c.name != "embedding"]
        return {column.name: getattr(self, column.name) for column in columns}


class ChatRunModel(Base):
    """One row per orchestrated chat turn: full envelopes as JSONB plus
    promoted stats (ok, duration, tokens) for cheap querying in eval."""

    __tablename__ = "chat_runs"

    chat_id = Column(String, primary_key=True)
    session_id = Column(String, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user_message = Column(Text, nullable=True)

    # promoted stats: cheap to query, index, aggregate
    ok = Column(Boolean, nullable=True)
    runtime_error = Column(Text, nullable=True)
    duration_s = Column(Float, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    # promoted out of planner.output.diagram so the review page (and any
    # querying) doesn't need to unpack the JSONB envelope just to render it
    mermaid = Column(Text, nullable=True)

    # full-fidelity envelopes: parse/strategy results live inside planner,
    # per-task executor results (one turn can run several) live inside tasks
    planner = Column(JSONB, nullable=True)
    tasks = Column(JSONB, nullable=True)

    # SSE transcript: exactly what the user saw this turn, in order, with
    # t/t_end second-offsets for replay pacing. Consecutive content.delta
    # chars are coalesced into sections (see SSEStream.flush_chars), so this
    # stays compact. Own column so replay reads skip the planner/tasks blobs.
    sse_events = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<ChatRunModel(chat_id='{self.chat_id}', session_id='{self.session_id}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in ChatRunModel.__table__.columns}
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row


class FeedbackModel(Base):
    """One review of a chat run from the internal /review page: the
    reviewer's overall like/dislike plus a JSONB list of
    {title, message, positive} comments. One row per (chat_id, session_id) —
    session_id is the *reviewing* session, not the one that produced the
    run — upserted whole on re-submit (see feedback_review_idx). chat_id is
    unenforced (no FK) so a review can reference a run whose row hasn't been
    recorded yet. A run's review count is derived by counting rows here,
    never stored on chat_runs."""

    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    chat_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False)
    # overall like/dislike; optional when the review carries comments
    liked = Column(Boolean, nullable=True)
    # list of {title, message, positive}; replaced whole on each submit
    comments = Column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self):
        return f"<FeedbackModel(id='{self.id}', chat_id='{self.chat_id}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in FeedbackModel.__table__.columns}
        for ts in ("created_at", "updated_at"):
            if row.get(ts) is not None:
                row[ts] = row[ts].isoformat()
        return row
