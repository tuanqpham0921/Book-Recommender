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

class HealthStatus(BaseModel):
    """Health check response model."""

    orchestrator: bool = False
    sqlalchemy_engine: bool = False
    message: str = "Service status"