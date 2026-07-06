from typing import TypeVar, Generic, List, Any, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from abc import ABC

from db.stores.utils import compile_sql

T = TypeVar('T')

class BaseStore(Generic[T], ABC):
    """Base store with common database operations."""

    def __init__(self, session: AsyncSession, model_class: type[T]):
        self.session = session
        self.model = model_class

    async def _execute_statement(self, stmt):
        try:
            print("------ STMT ------")
            print(compile_sql(stmt))
            print("------------------")
            result = await self.session.execute(stmt)
            return result
        except Exception as e:
            raise e