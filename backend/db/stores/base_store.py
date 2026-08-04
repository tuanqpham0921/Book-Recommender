import logging
from typing import TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from abc import ABC

from db.stores.utils import compile_sql

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseStore(Generic[T], ABC):
    """Base store with common database operations."""

    def __init__(self, session: AsyncSession, model_class: type[T]):
        self.session = session
        self.model = model_class

    async def execute_statement(self, stmt):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Executing statement: %s", compile_sql(stmt))
        return await self.session.execute(stmt)
