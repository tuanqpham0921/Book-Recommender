from pydantic import BaseModel

class SessionOut(BaseModel):
    id: str
    created_at: str

class ChatIn(BaseModel):
    message: str

class ChatRunFeedbackIn(BaseModel):
    """User feedback on one chat run; omitted fields are left untouched."""

    liked: bool | None = None
    comment: str | None = None

class HealthStatus(BaseModel):
    """Health check response model."""

    orchestrator: bool = False
    sqlalchemy_engine: bool = False
    message: str = "Service status"