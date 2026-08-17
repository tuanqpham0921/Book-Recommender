"""Query builders for book-related database operations.

Two families: `build_*_search` returns a statement run for rows straight away;
`build_*_query` / `build_count` / `compose` / `build_materialize` are the
deferred family, carried between nodes and executed for rows exactly once, at
the end. See docs/design/execution-pipeline-v1.md.
"""

from sqlalchemy import select, func, or_, text, union, intersect
from sqlalchemy.orm import defer
from db.stores.deferred_query import DeferredBookQuery
from typing import List


def compile_sql(stmt):
    """Compile SQLAlchemy statement to actual SQL string with formatting."""
    try:
        compiled = stmt.compile(
            compile_kwargs={"literal_binds": True, "render_postcompile": True}
        )
        return str(compiled)
    except Exception:
        # fallback without literal binds
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

    Takes no `BooksFilter`: metadata narrowing is Filter_Retrieval's job in the
    deferred pipeline, applied to the composed query rather than to this one.
    """
    embed_col = getattr(model, embedding_column)

    stmt = select(
        model,
        # cosine similarity = 1 - cosine distance
        (1 - embed_col.cosine_distance(query_embedding)).label("similarity_score"),
    ).where(embed_col.is_not(None))

    stmt = stmt.order_by(text("similarity_score DESC"))
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
    """A small sample of the match and its total size, in one statement.

    `count(*) OVER ()` is evaluated before LIMIT, so `total` is the whole match
    while the rows are the sample — one round trip, and no way for the two to
    disagree.

    Ranks by the query's own `score` when it has one, by popularity otherwise.
    `ratings_count`, not `average_rating`: a sample should be books people
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

    `"or"` pools (the implicit-union rule), `"and"` intersects; Postgres dedups
    by isbn13 either way. Only isbn13 survives — a per-dimension `score` means
    nothing once two dimensions combine — so a single input passes through
    untouched and keeps its score.
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
    back to the books table. Ranks by the query's own `score` when it still has
    one, by rating otherwise — a composition leaves no score to rank on.
    """
    src = query.cte("final")
    stmt = select(model).join(src, model.isbn13 == src.c.isbn13)
    # ~6KB a row and nothing downstream reads it; raiseload makes an accidental
    # access a clear error rather than a lazy load that deadlocks under asyncio
    stmt = stmt.options(defer(model.embedding, raiseload=True))
    if "score" in src.c.keys():
        stmt = stmt.order_by(src.c.score.desc())
    else:
        stmt = stmt.order_by(model.average_rating.desc().nulls_last())
    return stmt.limit(limit)
