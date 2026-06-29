import logging
from pydantic import BaseModel, ConfigDict

from common.utils import now_iso
from app.common.messages import UserMessage
from db.stores.book_store import BookStore
from app.common.sse_stream import SSEStream

from clients import OpenAIClient

logger = logging.getLogger(__name__)


class RequestContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    app_env: str

    session_id: str
    user_message: UserMessage

    llm_client: OpenAIClient
    book_store: BookStore
    sse_stream: SSEStream
