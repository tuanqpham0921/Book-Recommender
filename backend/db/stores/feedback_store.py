from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.utils import uuid_8
from db.schema import FeedbackModel
from .base_store import BaseStore


class FeedbackStore(BaseStore[FeedbackModel]):
    """SQLAlchemy-based feedback / bug report data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, FeedbackModel)

    async def create(
        self,
        message: str,
        title: Optional[str] = None,
        positive: Optional[bool] = None,
        chat_id: Optional[str] = None,
        session_id: Optional[str] = None,
        review: bool = False,
    ) -> FeedbackModel:
        """Insert one feedback entry. chat_id/session_id are both optional —
        works fine for a general bug report tied to neither. review marks
        whether this was filed from the internal /review page rather than
        the live chat's end-user feedback widget."""
        row = FeedbackModel(
            id=f"fb_{uuid_8()}",
            session_id=session_id,
            chat_id=chat_id,
            title=title,
            message=message,
            positive=positive,
            review=review,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def upsert_reaction(
        self,
        chat_id: str,
        session_id: str,
        liked: bool,
        review: bool = True,
    ) -> FeedbackModel:
        """Set (or change) one reviewer's like/dislike reaction to a run.
        One row per (chat_id, session_id) — a second call from the same
        reviewer session updates the existing row instead of adding another,
        unlike the append-only issue/praise log."""
        stmt = (
            insert(FeedbackModel)
            .values(
                id=f"fb_{uuid_8()}",
                session_id=session_id,
                chat_id=chat_id,
                liked=liked,
                review=review,
            )
            .on_conflict_do_update(
                index_elements=[FeedbackModel.chat_id, FeedbackModel.session_id],
                index_where=FeedbackModel.liked.isnot(None),
                set_={"liked": liked},
            )
            .returning(FeedbackModel)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()

    async def get_by_chat_id(self, chat_id: str) -> List[FeedbackModel]:
        """Get all feedback entries filed against one chat run, oldest first."""
        stmt = (
            select(FeedbackModel)
            .where(FeedbackModel.chat_id == chat_id)
            .order_by(FeedbackModel.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
