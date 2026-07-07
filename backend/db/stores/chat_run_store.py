from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.schema import ChatRunModel
from .base_store import BaseStore


class ChatRunStore(BaseStore[ChatRunModel]):
    """SQLAlchemy-based chat run data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ChatRunModel)

    async def insert_run(self, row: Dict[str, Any]) -> None:
        """Insert one chat run row (keys must match ChatRunModel columns)."""
        self.session.add(ChatRunModel(**row))
        await self.session.commit()

    async def get_by_session(
        self, session_id: str, limit: int = 50
    ) -> List[ChatRunModel]:
        """Get a session's chat runs, newest first."""
        stmt = (
            select(ChatRunModel)
            .where(ChatRunModel.session_id == session_id)
            .order_by(ChatRunModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self, limit: int = 200, offset: int = 0) -> List[ChatRunModel]:
        """Get all chat runs, newest first (for the review page)."""
        stmt = (
            select(ChatRunModel)
            .order_by(ChatRunModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_feedback(
        self,
        chat_id: str,
        liked: Optional[bool] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """Set user feedback on a run. Only overwrites the fields provided.

        Returns False when no row matches chat_id."""
        values: Dict[str, Any] = {}
        if liked is not None:
            values["liked"] = liked
        if comment is not None:
            values["comment"] = comment
        if not values:
            return True

        stmt = (
            update(ChatRunModel)
            .where(ChatRunModel.chat_id == chat_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
