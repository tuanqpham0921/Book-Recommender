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

    # prior turns for this session (read-only seed, loaded once by the
    # request context factory) — see ConversationOrchestrator.run for how
    # this seeds pipeline_message
    chat_messages: list[APIMessage] = Field(default_factory=list)
    # this turn's full message trace: chat_messages + everything the
    # workflows generate; persisted into chat_runs.orchestration
    pipeline_message: list[APIMessage] = Field(default_factory=list)

    llm_client: OpenAIClient
    book_store: BookStore
    sse_stream: SSEStream

    # for writes that outlive the request-scoped session (e.g. chat run records)
    session_factory: async_sessionmaker[AsyncSession]
