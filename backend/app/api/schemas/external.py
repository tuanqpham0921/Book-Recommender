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

ChatRunIssueCategory = Literal["Inaccurate", "Hallucination", "UI", "Other"]

class ChatRunIssueIn(BaseModel):
    """One entry appended to a chat run's issue log."""

    title: ChatRunIssueCategory
    message: str
    positive: bool

class HealthStatus(BaseModel):
    """Health check response model."""

    orchestrator: bool = False
    sqlalchemy_engine: bool = False
    message: str = "Service status"