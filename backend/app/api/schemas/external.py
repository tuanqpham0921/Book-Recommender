from typing import Literal

from pydantic import BaseModel

class SessionOut(BaseModel):
    id: str
    created_at: str

class ChatIn(BaseModel):
    message: str

class ChatRunFeedbackIn(BaseModel):
    """Like/dislike reaction on one chat run; omitted field is left untouched."""

    liked: bool | None = None

FeedbackCategory = Literal["Content", "Recommendation", "Planner", "Time", "UI/UX", "Other"]

class FeedbackIn(BaseModel):
    """One feedback / bug report entry. chat_id is optional — omit it for
    reports not tied to a specific query (general bug reports)."""

    chat_id: str | None = None
    session_id: str | None = None
    title: FeedbackCategory | None = None
    message: str
    positive: bool
    review: bool = False

class HealthStatus(BaseModel):
    """Health check response model."""

    orchestrator: bool = False
    sqlalchemy_engine: bool = False
    message: str = "Service status"