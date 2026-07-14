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

    async def get_all(
        self,
        limit: int = 200,
        offset: int = 0,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get chat runs, newest first (for the review page); optionally only
        those whose session_id contains the given search string."""
        stmt = select(ChatRunModel).order_by(ChatRunModel.created_at.desc())
        if session_id:
            stmt = stmt.where(ChatRunModel.session_id.ilike(f"%{session_id}%"))
        stmt = stmt.limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        return [run.to_dict() for run in result.scalars().all()]

    async def update_feedback(
        self,
        chat_id: str,
        liked: Optional[bool] = None,
        reviewed: Optional[bool] = None,
    ) -> bool:
        """Set the like/dislike reaction and/or the reviewed flag on a run;
        omitted (None) fields are left untouched.

        Returns False when no row matches chat_id."""
        values: Dict[str, Any] = {}
        if liked is not None:
            values["liked"] = liked
        if reviewed is not None:
            values["reviewed"] = reviewed
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
