from typing import List, Optional, Any, Dict, cast
from sqlalchemy.ext.asyncio import AsyncSession
from db.schema import BooksFilter

from db.schema import BookModel
from .base_store import BaseStore
from .utils import build_title_search, build_embedding_search


class BookStore(BaseStore[BookModel]):
    """SQLAlchemy-based book data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, BookModel)

    async def search_by_title(
        self, title: str, limit: int = 10, similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Search books by title with fuzzy matching."""

        stmt = build_title_search(self.model, title, limit, similarity_threshold)
        result = await self.execute_statement(stmt)
        rows = result.scalars().all()
        return [row.to_dict() for row in rows]

    async def search_by_embedding(
        self,
        query_embedding: List[float],
        filters: Optional[BooksFilter] = None,
        similarity_threshold: float = 0.7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search books using embedding similarity."""

        stmt = build_embedding_search(
            self.model, query_embedding, filters, similarity_threshold, limit
        )

        result = await self.execute_statement(stmt)
        rows = result.all()

        # Convert to dicts and include similarity scores
        books_with_scores = []
        for row in rows:
            book_dict = self.row_to_dict(row[0])  # The book object
            book_dict["similarity_score"] = float(row[1])  # The similarity score
            books_with_scores.append(book_dict)

        return books_with_scores
