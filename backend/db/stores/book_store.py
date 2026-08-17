from typing import List, Any, Dict

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.schema import BookModel
from .base_store import BaseStore
from .deferred_query import DeferredBookQuery


class BookStore(BaseStore[BookModel]):
    """SQLAlchemy-based book data access layer.

    The store builds queries from a search dimension (which needs the model)
    and executes statements (which needs the session). What can be derived
    from an already-built query — counting it, materializing it, pooling
    several — lives on `DeferredBookQuery` itself.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, BookModel)

    async def search_by_embedding(
        self,
        query_embedding: List[float],
        similarity_threshold: float = 0.7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search books using embedding similarity.

        Takes no `BooksFilter`: metadata narrowing is Filter_Retrieval's job in
        the deferred pipeline, applied to the composed query rather than here.
        """
        embed_col = self.model.embedding
        stmt = (
            select(
                self.model,
                # cosine similarity = 1 - cosine distance
                (1 - embed_col.cosine_distance(query_embedding)).label(
                    "similarity_score"
                ),
            )
            .where(embed_col.is_not(None))
            .order_by(text("similarity_score DESC"))
            .limit(limit)
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
        """Build the title search without running it: isbn13 plus the fuzzy
        score, with no ORDER BY and no LIMIT so the result can be composed
        into a CTE."""
        stmt = select(
            self.model.isbn13,
            func.similarity(self.model.title, title).label("score"),
        ).where(
            or_(
                self.model.title.ilike(f"{title}"),
                func.similarity(self.model.title, title) > similarity_threshold,
            )
        )
        return DeferredBookQuery(stmt, label="title")

    async def count(self, query: DeferredBookQuery) -> int:
        """How many books the query matches. Zero is an answer, not a failure."""
        result = await self.execute_statement(query.count_stmt())
        return int(result.scalar_one())

    async def materialize(
        self, query: DeferredBookQuery, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Run a deferred query for rows — the last step of a plan."""
        result = await self.execute_statement(query.materialize_stmt(self.model, limit))
        return [row.to_dict() for row in result.scalars().all()]
