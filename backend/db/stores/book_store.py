from typing import List, Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from db.schema import BookModel
from .base_store import BaseStore
from .deferred_query import DeferredBookQuery
from .utils import (
    build_count,
    build_embedding_search,
    build_materialize,
    build_title_query,
)


class BookStore(BaseStore[BookModel]):
    """SQLAlchemy-based book data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, BookModel)

    async def search_by_embedding(
        self,
        query_embedding: List[float],
        similarity_threshold: float = 0.7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search books using embedding similarity."""

        stmt = build_embedding_search(
            self.model, query_embedding, similarity_threshold, limit
        )

        result = await self.execute_statement(stmt)
        rows = result.all()

        # Convert to dicts and include similarity scores
        books_with_scores = []
        for row in rows:
            book_dict = row[0].to_dict()  # The book object
            book_dict["similarity_score"] = float(row[1])  # The similarity score
            books_with_scores.append(book_dict)

        return books_with_scores

    # --- deferred queries: build now, count now, fetch rows once at the end ---

    def title_query(
        self, title: str, similarity_threshold: float = 0.7
    ) -> DeferredBookQuery:
        """Build the title search without running it."""
        return DeferredBookQuery(
            build_title_query(self.model, title, similarity_threshold),
            label="title",
        )

    async def count(self, query: DeferredBookQuery) -> int:
        """How many books the query matches. Zero is an answer, not a failure."""
        result = await self.execute_statement(build_count(query))
        return int(result.scalar_one())

    async def materialize(
        self, query: DeferredBookQuery, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Run a deferred query for rows — the last step of a plan."""
        stmt = build_materialize(query, self.model, limit)
        result = await self.execute_statement(stmt)
        return [row.to_dict() for row in result.scalars().all()]
