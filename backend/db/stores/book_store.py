from typing import List, Optional, Any, Dict, cast
from sqlalchemy.ext.asyncio import AsyncSession
from db.schema import BooksFilter

from db.schema import BookModel
from .base_store import BaseStore
from .utils import (
    build_title_search,
    build_isbn_search,
    build_filtered_search,
    build_embedding_search
)

from sqlalchemy import select, func
from typing import AsyncIterator

class BookStore(BaseStore[BookModel]):
    """SQLAlchemy-based book data access layer."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, BookModel)

    async def get_by_isbn(self, isbn: str) -> List[Dict[str, Any]]:
        """Get a single book by ISBN-13"""
        
        stmt = build_isbn_search(self.model, isbn)
        result = await self._execute_statement(stmt)
        row = result.scalars().first()
        return [self.row_to_dict(row)] if row else []

    async def search_by_title(
        self, title: str, limit: int = 10, similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Search books by title with fuzzy matching."""
        
        stmt = build_title_search(self.model, title, limit, similarity_threshold)
        result = await self._execute_statement(stmt)
        rows = result.scalars().all()
        return [self.row_to_dict(row) for row in rows]
    
    async def search_by_filters(
        self, 
        filters: BooksFilter,
    ) -> List[Dict[str, Any]]:
        """Search books using structured filters."""
        
        stmt = build_filtered_search(self.model, filters)
        result = await self._execute_statement(stmt)
        rows = result.scalars().all()
        return [self.row_to_dict(row) for row in rows]

    async def search_by_book_filter(
        self, 
        filters: BooksFilter,
    ) -> List[Dict[str, Any]]:
        """Search books separately per author, then combine results."""
        
        if not filters.authors:
            # No authors specified, use regular search
            return await self.search_by_filters(filters)
        
        all_results = []
        
        # to ensure we have each authors in the results
        for author_name in filters.authors:
            # Create a filter for just this author
            author_filter = filters.model_copy(
                update={"authors": [author_name]},
                deep=True
            )
            
            results = await self.search_by_filters(author_filter)
            all_results.extend(results)
        
        # Remove duplicates (in case a book appears for multiple authors)
        seen_isbns = set()
        unique_results = []
        for book in all_results:
            if book.get('isbn13') not in seen_isbns:
                unique_results.append(book)
                seen_isbns.add(book.get('isbn13'))
        
        return unique_results
    
    async def search_by_embedding(
        self,
        query_embedding: List[float],
        filters: Optional[BooksFilter] = None,
        similarity_threshold: float = 0.7,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search books using embedding similarity."""
        
        stmt = build_embedding_search(
            self.model,
            query_embedding,
            filters,
            similarity_threshold,
            limit
        )
        
        result = await self._execute_statement(stmt)
        rows = result.all()
        
        # Convert to dicts and include similarity scores
        books_with_scores = []
        for row in rows:
            book_dict = self.row_to_dict(row[0])  # The book object
            book_dict['similarity_score'] = float(row[1])  # The similarity score
            books_with_scores.append(book_dict)
        
        return books_with_scores
    
    
    async def iter_missing_embeddings(
        self,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream books missing embeddings."""
        stmt = (
            select(
                BookModel.isbn13,
                BookModel.title,
                BookModel.description,
            )
            .where(BookModel.embedding.is_(None))
            .where(BookModel.description.is_not(None))
            .execution_options(yield_per=batch_size)
        )
        result = await self.session.stream(stmt)
        async for row in result.mappings():
            yield dict(row)
    
    async def get_num_book_missing_embeddings(self) -> int:
        """Get the number of books that are missing embeddings."""
        stmt = select(func.count()).select_from(BookModel).where(BookModel.embedding.is_(None))
        result = await self.session.execute(stmt)
        # COUNT(*) always yields one row, so scalar() is never None here
        return cast(int, result.scalar())

    def row_to_dict(self, row: BookModel) -> Dict[str, Any]:
        """Convert BookModel to standardized dictionary."""
        if not row:
            return {}

        # cast: BookModel uses legacy Column declarations, so pyright sees
        # instance attributes as Column objects instead of their values
        isbn13 = cast(Optional[str], row.isbn13)
        average_rating = cast(Optional[float], row.average_rating)
        thumbnail = cast(Optional[str], row.thumbnail)

        return {
            "isbn13": isbn13,
            "title": row.title,
            "authors": row.authors,
            "categories": row.categories,
            "published_year": row.published_year,
            "num_pages": row.num_pages,
            "average_rating": float(average_rating) if average_rating else None,
            "description": row.description,
            "thumbnail": (
                thumbnail
                or f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg"
                if isbn13
                else "data/cover-not-found.jpg"
            ),
            "ratings_count": row.ratings_count,
            "genre": row.genre,
            "is_children": row.is_children
        }
