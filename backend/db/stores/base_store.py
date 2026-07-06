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

    async def get_by_id(self, id: Any) -> Any:
        """Get entity by primary key.

        NOTE: returns the raw SQLAlchemy Result (callers must extract the
        row) — annotated Any to reflect that until this is cleaned up.
        """
        # getattr: T is a bare TypeVar, so pyright can't see model columns
        model_id = getattr(self.model, "id")
        return await self._execute_statement(select(self.model).where(model_id == id))

    async def get_all(self, limit: int = 100) -> List[T]:
        """Get all entities with limit."""
        stmt = select(self.model).limit(limit)
        result = await self._execute_statement(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total entities."""
        from sqlalchemy import func
        stmt = select(func.count(getattr(self.model, "id")))
        result = await self._execute_statement(stmt)
        # COUNT(*) always yields one row, so scalar() is never None here
        return cast(int, result.scalar())