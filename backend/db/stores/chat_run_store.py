import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import cast, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
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

    async def get_by_chat_id(self, chat_id: str) -> Optional[ChatRunModel]:
        """Get a single chat run by its chat_id."""
        stmt = select(ChatRunModel).where(ChatRunModel.chat_id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def append_issue(
        self, chat_id: str, title: str, message: str, positive: bool
    ) -> Optional[List[Dict[str, Any]]]:
        """Append one entry to a chat run's issue log (JSONB array), atomically
        via Postgres' `||` concat — safe under concurrent appends since the
        read-modify-write happens server-side, not in application code.

        Returns the updated issue log, or None if no row matches chat_id."""
        entry = {
            "title": title,
            "message": message,
            "positive": positive,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        new_entry = cast(literal(json.dumps([entry])), JSONB)
        stmt = (
            update(ChatRunModel)
            .where(ChatRunModel.chat_id == chat_id)
            .values(comment=ChatRunModel.comment.op("||")(new_entry))
            .returning(ChatRunModel.comment)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        row = result.first()
        return row[0] if row else None

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
    ) -> bool:
        """Set the like/dislike reaction on a run.

        Returns False when no row matches chat_id."""
        values: Dict[str, Any] = {}
        if liked is not None:
            values["liked"] = liked
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
