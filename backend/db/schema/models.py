# SQLAlchemy models (shared by stores / DB layers)
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Float, Text, Boolean, func
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
    # promoted out of planner.response.result.diagram so the review page does
    # not have to unpack the JSONB envelope to render it
    mermaid = Column(Text, nullable=True)

    # full-fidelity envelopes: parse/strategy results live inside planner,
    # per-task executor results (one turn can run several) live inside tasks
    planner = Column(JSONB, nullable=True)
    tasks = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<ChatRunModel(chat_id='{self.chat_id}', session_id='{self.session_id}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in ChatRunModel.__table__.columns}
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row


class FeedbackModel(Base):
    """One review of a chat run from the internal /review page: an overall
    like/dislike plus a JSONB list of {title, message, positive} comments.

    One row per (chat_id, session_id) — session_id is the *reviewing* session —
    upserted whole on re-submit (see feedback_review_idx). chat_id CASCADEs from
    chat_runs. A run's review count is counted from these rows, never stored."""

    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    chat_id = Column(
        String,
        ForeignKey("chat_runs.chat_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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


class TestRunModel(Base):
    """Links an eval-suite case to the chat run it produced: suite file stem
    plus the entry id inside it. Written by evals/run_suites.py; evals/report.py
    joins it with chat_runs. CASCADE so wiping chat_runs auto-cleans these."""

    __tablename__ = "test_runs"

    chat_id = Column(
        String, ForeignKey("chat_runs.chat_id", ondelete="CASCADE"), primary_key=True
    )
    suite_name = Column(Text, nullable=False)
    suite_case_id = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self):
        return (
            f"<TestRunModel(chat_id='{self.chat_id}', "
            f"suite='{self.suite_name}#{self.suite_case_id}')>"
        )

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in TestRunModel.__table__.columns}
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row
