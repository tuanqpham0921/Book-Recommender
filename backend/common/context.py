import os
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients import OpenAIClient
from config import Settings
from db.async_engine import close_async_engine, get_async_engine, get_session_factory
import logging

logger = logging.getLogger(__name__)

class AppContext:
    app_env: str
    engine: AsyncEngine
    openai_client: OpenAIClient
    session_factory: async_sessionmaker[AsyncSession]
    
    def __init__(self, settings: Settings) -> None:
        logger.info("Initializing AppContext")
        
        self.engine = get_async_engine(settings.sqlalchemy)
        logger.info("Engine initialized")
        
        self.openai_client = OpenAIClient(settings.openai)
        logger.info("OpenAI client initialized")
        
        self.session_factory = get_session_factory(self.engine)
        logger.info("Session factory initialized")
        
        self.app_env = settings.app.ENVIRONMENT
        logger.info("App environment set")
        
    async def __aenter__(self) -> "AppContext":
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        
        await close_async_engine(self.engine)
        logger.info("Closed SQLAlchemy engine")
        
        await self.openai_client.close()
        logger.info("Closed OpenAI client")