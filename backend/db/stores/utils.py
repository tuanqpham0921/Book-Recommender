"""Query builder for book-related database operations."""

from sqlalchemy import select, func, or_, and_, text
from db.schema import BooksFilter
from typing import Optional, List


def compile_sql(stmt):
    """Compile SQLAlchemy statement to actual SQL string with formatting."""
    try:
        # Compile with literal binds to show actual values
        compiled = stmt.compile(
            compile_kwargs={
                "literal_binds": True,  # Shows actual parameter values
                "render_postcompile": True,  # Handles modern SQLAlchemy features
            }
        )
        return str(compiled)
    except Exception as e:
        # Fallback without literal binds if that fails
        return str(stmt.compile())


def build_title_search(
    model,
    book_title: str,
    limit: int = 1,
    similarity_threshold: float = 0.7,
):
    """Apply title-based filtering with similarity search."""
    stmt = select(model)
    stmt = stmt.where(
        or_(
            model.title.ilike(f"%{book_title}%"),
            func.similarity(model.title, book_title) > similarity_threshold,
        )
    )

    stmt = stmt.order_by(func.similarity(model.title, book_title).desc())
    stmt = stmt.limit(limit)
    return stmt


def build_embedding_search(
    model,
    query_embedding: List[float],
    filters: Optional[BooksFilter] = None,
    similarity_threshold: float = 0.7,
    limit: int = 50,
    embedding_column: str = "embedding",
):
    """Build embedding similarity search query with optional filters."""

    # Get the embedding column
    embed_col = getattr(model, embedding_column)

    # Base query with cosine similarity
    stmt = select(
        model,
        # Calculate cosine similarity (1 - cosine distance)
        (1 - embed_col.cosine_distance(query_embedding)).label("similarity_score"),
    ).where(
        # Only include books with embeddings
        embed_col.is_not(None)
    )
    # ).filter(
    #     # Similarity threshold
    #     # embed_col.cosine_distance(query_embedding) < (1 - similarity_threshold)
    # )
    
    # Apply additional filters if provided
    if filters:
        # Copy with the limit zeroed out so the caller's filter limit doesn't
        # apply here — the similarity limit below takes precedence instead
        stmt = apply_book_filters(
            stmt,
            model,
            filters.model_copy(update={"limit": 0}),
            similarity_threshold=similarity_threshold,
            fuzzy_limit=10,
        )

    # Order by similarity score (highest first) - this takes precedence
    stmt = stmt.order_by(text("similarity_score DESC"))

    # Apply limit
    stmt = stmt.limit(limit)

    return stmt
