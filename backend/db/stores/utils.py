"""Query builders for book-related database operations.

Two families live here. `build_*_search` returns a statement that is run for
rows straight away. `build_*_query` / `build_count` / `compose` /
`build_materialize` are the **deferred** family: they build a statement that
gets carried between nodes and executed for rows exactly once, at the end.
See docs/design/execution-pipeline-v1.md.
"""

from sqlalchemy import select, func, or_, and_, text, union, intersect
from sqlalchemy.orm import defer
from db.schema import BooksFilter
from db.stores.deferred_query import DeferredBookQuery
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
    similarity_threshold: float = 0.7,
    limit: int = 50,
    embedding_column: str = "embedding",
):
    """Build embedding similarity search query.

    Took a `BooksFilter` until the branch trim removed `apply_book_filters`;
    the parameter is gone rather than silently ignored. Metadata narrowing is
    Filter_Retrieval's job in the deferred pipeline, applied to the composed
    query instead of to this one.
    """

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

    # Order by similarity score (highest first) - this takes precedence
    stmt = stmt.order_by(text("similarity_score DESC"))

    # Apply limit
    stmt = stmt.limit(limit)

    return stmt


# --- deferred family: built here, executed once at the end of the plan -------


def build_title_query(
    model,
    book_title: str,
    similarity_threshold: float = 0.7,
):
    """Deferred form of `build_title_search`: isbn13 plus the fuzzy score, with
    no ORDER BY and no LIMIT so the result can be composed into a CTE."""
    return select(
        model.isbn13,
        func.similarity(model.title, book_title).label("score"),
    ).where(
        or_(
            model.title.ilike(f"{book_title}"),
            func.similarity(model.title, book_title) > similarity_threshold,
        )
    )

def build_count(query: DeferredBookQuery):
    """COUNT over a deferred query without materializing its rows."""
    return select(func.count()).select_from(query.cte("matched"))

def build_preview(query: DeferredBookQuery, model, limit: int = 3):
    """A small sample of the match **and** its total size, in one statement.

    `count(*) OVER ()` is evaluated before LIMIT, so `total` is the size of the
    whole match while the rows are only the sample. One round trip instead of a
    COUNT plus a SELECT, and no way for the two to disagree.

    Ranks by the query's own `score` when it has one — you searched for "Dune",
    so Dune should lead — and by popularity otherwise. `ratings_count`, not
    `average_rating`: a sample of a 1,200-book match should be books people
    recognize, and top-rated surfaces obscure 5.0s with three ratings.
    """
    src = query.cte("preview_src")
    stmt = (
        select(model, func.count().over().label("total"))
        .join(src, model.isbn13 == src.c.isbn13)
        .options(defer(model.embedding, raiseload=True))
    )
    if "score" in src.c.keys():
        stmt = stmt.order_by(src.c.score.desc())
    else:
        stmt = stmt.order_by(model.ratings_count.desc().nulls_last())
    return stmt.limit(limit)


def compose(queries: List[DeferredBookQuery], op: str = "or"):
    """Compose deferred queries into one statement via a WITH clause.

    `"or"` pools — the implicit-union rule, where several `depends_on` ids
    mean "pool what all of these found". `"and"` intersects. Postgres dedups
    by isbn13 for both, so the pooling rule costs the executors nothing.

    Only isbn13 survives a composition: a per-dimension `score` stops meaning
    anything once two dimensions are combined. A single input is passed
    through untouched so it keeps its score.
    """
    if not queries:
        raise ValueError("compose() needs at least one query")
    if len(queries) == 1:
        return queries[0].stmt

    # positional names, because two nodes can legitimately carry the same label
    parts = [select(q.cte(f"q{i}").c.isbn13) for i, q in enumerate(queries)]
    combined = (union if op == "or" else intersect)(*parts).cte("combined")
    return select(combined.c.isbn13)


def build_materialize(query: DeferredBookQuery, model, limit: int = 10):
    """The one statement that returns books: join the deferred query's isbn13s
    back to the books table.

    Ranks by the query's own `score` when it still has one (a single-dimension
    query), and by rating otherwise — after a composition there is no
    cross-dimension score to rank on.
    """
    src = query.cte("final")
    stmt = select(model).join(src, model.isbn13 == src.c.isbn13)
    # the vector column is ~6KB a row and nothing downstream reads it;
    # raiseload makes an accidental access a clear error rather than a lazy
    # load that would deadlock under asyncio
    stmt = stmt.options(defer(model.embedding, raiseload=True))
    if "score" in src.c.keys():
        stmt = stmt.order_by(src.c.score.desc())
    else:
        stmt = stmt.order_by(model.average_rating.desc().nulls_last())
    return stmt.limit(limit)
