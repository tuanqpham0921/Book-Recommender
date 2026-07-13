from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.schema import ChatRunModel, FeedbackModel
from .base_store import BaseStore


class ChatRunStore(BaseStore[ChatRunModel]):
    """SQLAlchemy-based chat run data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ChatRunModel)

    async def _list_with_feedback(
        self, limit: int, offset: int, where=None
    ) -> List[Dict[str, Any]]:
        """Shared query for get_all/get_test_runs: chat_runs rows, newest
        first, left-joined against a per-chat_id aggregate of the feedback
        table so the review page can show reviewer reactions and written
        reports without an extra request per row.

        reviewer_liked / reviewer_disliked: any feedback row (from any
        reviewer session) reacted this way. has_report: any feedback row
        left a written message. All independent of chat_runs.liked, which
        is the original end user's own reaction."""
        fb = (
            select(
                FeedbackModel.chat_id,
                func.bool_or(FeedbackModel.liked.is_(True)).label("reviewer_liked"),
                func.bool_or(FeedbackModel.liked.is_(False)).label(
                    "reviewer_disliked"
                ),
                func.bool_or(FeedbackModel.message.is_not(None)).label("has_report"),
            )
            .group_by(FeedbackModel.chat_id)
            .subquery()
        )
        stmt = (
            select(
                ChatRunModel,
                fb.c.reviewer_liked,
                fb.c.reviewer_disliked,
                fb.c.has_report,
            )
            .outerjoin(fb, fb.c.chat_id == ChatRunModel.chat_id)
            .order_by(ChatRunModel.created_at.desc())
        )
        if where is not None:
            stmt = stmt.where(where)
        stmt = stmt.limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        rows = []
        for run, reviewer_liked, reviewer_disliked, has_report in result.all():
            row = run.to_dict()
            row["reviewer_liked"] = bool(reviewer_liked)
            row["reviewer_disliked"] = bool(reviewer_disliked)
            row["has_report"] = bool(has_report)
            rows.append(row)
        return rows

    async def insert_run(self, row: Dict[str, Any]) -> None:
        """Insert one chat run row (keys must match ChatRunModel columns)."""
        self.session.add(ChatRunModel(**row))
        await self.session.commit()

    async def get_all(self, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        """Get all chat runs, newest first (for the review page), each
        annotated with reviewer_liked/reviewer_disliked/has_report from the
        feedback table."""
        return await self._list_with_feedback(limit=limit, offset=offset)

    async def get_test_runs(
        self, limit: int = 200, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get chat runs from test suites, newest first (session_id contains
        "test_", matching the prefix test suites mint their session_ids
        with), same feedback annotations as get_all."""
        return await self._list_with_feedback(
            limit=limit,
            offset=offset,
            where=ChatRunModel.session_id.ilike("%test_%"),
        )

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
