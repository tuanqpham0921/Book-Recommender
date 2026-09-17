from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.utils import uuid_8
from db.schema import FeedbackModel
from .base_store import BaseStore


class FeedbackStore(BaseStore[FeedbackModel]):
    """SQLAlchemy-based review data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, FeedbackModel)

    async def upsert_review(
        self,
        chat_id: str,
        session_id: str,
        liked: Optional[bool],
        comments: List[Dict[str, Any]],
    ) -> FeedbackModel:
        """Insert or replace one reviewing session's review of a run. One row
        per (chat_id, session_id): re-submitting from the same session
        replaces liked and the whole comments list rather than merging, so
        the client always sends the full review."""
        stmt = (
            insert(FeedbackModel)
            .values(
                id=f"fb_{uuid_8()}",
                chat_id=chat_id,
                session_id=session_id,
                liked=liked,
                comments=comments,
            )
            .on_conflict_do_update(
                index_elements=[FeedbackModel.chat_id, FeedbackModel.session_id],
                set_={
                    "liked": liked,
                    "comments": comments,
                    "updated_at": func.now(),
                },
            )
            .returning(FeedbackModel)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()

    async def get_by_chat_id(self, chat_id: str) -> List[FeedbackModel]:
        """Get all reviews of one chat run, oldest first."""
        stmt = (
            select(FeedbackModel)
            .where(FeedbackModel.chat_id == chat_id)
            .order_by(FeedbackModel.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
