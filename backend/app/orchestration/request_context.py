import logging
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.utils import now_iso
from app.common.messages import APIMessage, UserMessage
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

    # for writes that outlive the request-scoped session (e.g. chat run records)
    session_factory: async_sessionmaker[AsyncSession]

    # which query-suite entry produced this request, if any (see ChatIn);
    # recorded on the chat_runs row, None for real user chats
    suite_name: str | None = None
    suite_case_id: int | None = None
