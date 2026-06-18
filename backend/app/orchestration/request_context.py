import logging
from dataclasses import dataclass

from common.utils import now_iso
from app.common.messages import UserMessage
from db.stores.book_store import BookStore
from app.common.sse_stream import SSEStream

from clients import OpenAIClient

logger = logging.getLogger(__name__)

@dataclass
class RequestContext:
    """Enhanced request context with separated conversation streams."""
    app_env: str
    
    # Core identifiers
    session_id: str
    user_message: UserMessage

    # Services
    llm_client: OpenAIClient
    book_store: BookStore
    sse_stream: SSEStream