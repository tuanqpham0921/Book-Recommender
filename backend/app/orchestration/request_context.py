import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from app.common.enums import Role
from common.utils import now_iso, save_file
from app.common.messages import APIMessage, UserMessage, AssistantMessage, ToolMessage
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
    
    # in-domain message
    # TODO: move this elsewhere
    # need it for legacy reasons for now
    in_domain_message: str | None = None