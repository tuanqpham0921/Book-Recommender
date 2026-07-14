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

    # user feedback: liked is None until the user reacts (True = like, False = dislike)
    liked = Column(Boolean, nullable=True)

    # review-page bookkeeping: marked True once a reviewer is done with this
    # run, moving it out of the unreviewed list
    reviewed = Column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self):
        return f"<ChatRunModel(chat_id='{self.chat_id}', session_id='{self.session_id}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in ChatRunModel.__table__.columns}
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row


class FeedbackModel(Base):
    """Standalone feedback / bug report. chat_id and session_id are both
    optional and unenforced (no FK) so a report can be filed against an
    in-flight chat_id before its chat_runs row exists, or with neither
    (a general bug report not tied to any query)."""

    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    session_id = Column(String, nullable=True, index=True)
    chat_id = Column(String, nullable=True, index=True)
    title = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    positive = Column(Boolean, nullable=True)
    # True when filed from the internal /review page, False when filed by an
    # end user from the live chat's feedback widget.
    review = Column(Boolean, nullable=False, default=False, server_default="false")
    # A reviewer's like/dislike reaction to this run — distinct from
    # chat_runs.liked (the original end-user's own reaction). NULL for
    # ordinary issue/praise reports; one row per (chat_id, session_id) is
    # upserted when non-null (see feedback_reviewer_reaction_idx).
    liked = Column(Boolean, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self):
        return f"<FeedbackModel(id='{self.id}', chat_id='{self.chat_id}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary (table columns only)."""
        row = {c.name: getattr(self, c.name) for c in FeedbackModel.__table__.columns}
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row
