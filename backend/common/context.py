from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients import OpenAIClient
from config import Settings
from db.async_engine import close_async_engine, get_async_engine, get_session_factory

from config import setup_logging

class AppContext:
    engine: AsyncEngine
    openai_client: OpenAIClient
    session_factory: async_sessionmaker[AsyncSession]
    
    def __init__(self, settings: Settings) -> None:
        self.engine = get_async_engine(settings.sqlalchemy)
        self.openai_client = OpenAIClient(settings.openai)
        self.session_factory = get_session_factory(self.engine)
        setup_logging(environment=settings.app.ENVIRONMENT)
        
    async def __aenter__(self) -> "AppContext":
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await close_async_engine(self.engine)
        await self.openai_client.close()
        