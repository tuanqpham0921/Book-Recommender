import os
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients import OpenAIClient
from config import Settings
from db.async_engine import close_async_engine, get_async_engine, get_session_factory
import logging
from db.async_engine import check_connection
import asyncio
logger = logging.getLogger(__name__)

class AppContext:
    app_env: str
    engine: AsyncEngine
    openai_client: OpenAIClient
    session_factory: async_sessionmaker[AsyncSession]
    
    def __init__(self, settings: Settings) -> None:
        logger.info("Initializing AppContext")
        
        self.engine = get_async_engine(settings.sqlalchemy)        
        self.openai_client = OpenAIClient(settings.openai)
        self.session_factory = get_session_factory(self.engine)
        
        self.app_env = settings.app.ENVIRONMENT
        logger.info(f"App environment set to: {self.app_env.upper()}")
        
    async def ping_services(self) -> None:
        """Ping the services to make sure they are running."""
        await asyncio.wait_for(
            asyncio.gather(
                self.openai_client.ping(),
                check_connection(self.session_factory()),
            ), 
            timeout=10.0
        )
        logger.info("Pinging services Completed")
        
    async def __aenter__(self) -> "AppContext":
        await self.ping_services()
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        
        await close_async_engine(self.engine)
        await self.openai_client.close()
