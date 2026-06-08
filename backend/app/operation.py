from common.operation import OperationResult
from typing import List
from app.common.messages import APIMessage
from dataclasses import dataclass, field

@dataclass(slots=True)
class ChatResult(OperationResult):
    """Outcome of the chat process."""
    session_id: str | None = None
    conversation: List[APIMessage] = field(default_factory=list)