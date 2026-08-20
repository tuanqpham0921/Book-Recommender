from typing import List, Any, Dict

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from config import BookConstraints
from db.schema import BookMetadataFilter, BookModel
from .base_store import BaseStore
from .deferred_query import DeferredBookQuery


def metadata_predicates(model: type[BookModel], filters: BookMetadataFilter) -> list:
    """The WHERE terms one metadata filter stands for, for the caller to AND.

    Every bound is inclusive and independent, so the filter is read as a list
    of comparisons rather than a shape. A book whose column is NULL fails the
    comparison and drops out — an unknown page count is not "under 300 pages".
    """
    lower = (
        (filters.min_pages, model.num_pages),
        (filters.min_rating, model.average_rating),
        (filters.min_ratings_count, model.ratings_count),
        (filters.min_year, model.published_year),
    )
    upper = (
        (filters.max_pages, model.num_pages),
        (filters.max_rating, model.average_rating),
        (filters.max_ratings_count, model.ratings_count),
        (filters.max_year, model.published_year),
    )

    predicates = [column >= bound for bound, column in lower if bound is not None]
    predicates += [column <= bound for bound, column in upper if bound is not None]
    if filters.is_children is not None:
        predicates.append(model.is_children.is_(filters.is_children))
    return predicates


def embedding_search_stmt(
    query_embedding: List[float],
    filters: BookMetadataFilter | None = None,
    exclude_isbns: List[str] | None = None,
    similarity_threshold: float = BookConstraints.MIN_SIMILARITY,
    limit: int = 50,
) -> Select:
    """The books nearest an embedding, narrowed to those worth ranking.

    Pure and model-bound rather than a store method — like `metadata_predicates`,
    but returned rather than applied, so a caller can record it (`compile_sql`)
    before running it. That is the whole reason this is split out: the search
    returns rows in cosine order, and no `DeferredBookQuery` reproduces that
    order (see `RecommendationOutput`), so it can never be a deferred query
    whose statement rides downstream on its own — recording it has to happen
    here, at the one point something still holds it unexecuted.

    Three narrowings, all optional, and all of them have to land *inside* this
    statement rather than on its result: the search orders the whole table and
    truncates at `limit`, so anything applied afterwards is applied to an
    already-capped set.

    - `similarity_threshold` is the floor. Without it this returns the top
      `limit` rows however far away they are — the whole table, ordered and
      truncated — so an ask with no near match answers with strangers.
    - `filters` are the metadata bounds the recommend node parsed. An all-None
      filter contributes no predicates and is a harmless no-op, unlike
      `filter_query()` which refuses one: there narrowing is the node's whole
      job, so a no-op would report a count read as filtered.
    - `exclude_isbns` drops the books the ask already named. In SQL rather than
      in the caller, so the excluded rows do not eat `limit` slots.

    `embedding` is deferred with `raiseload=True`, matching `materialize_stmt`:
    the vector is ~4KB per row and nothing downstream reads it (`to_dict()`
    excludes it by default), so fetching it for 50 rows only to throw it away
    is a wasted round trip.
    """
    embed_col = BookModel.embedding
    # cosine similarity = 1 - cosine distance
    similarity = 1 - embed_col.cosine_distance(query_embedding)
    stmt = (
        select(BookModel, similarity.label("similarity_score"))
        # BookModel declares columns with plain Column(...), not Mapped[...],
        # so pyright sees Column[Unknown] here instead of the QueryableAttribute
        # `defer()`'s stub wants — same stub gap as `src.c.score` below.
        .options(defer(embed_col, raiseload=True))  # type: ignore[reportArgumentType]
        .where(embed_col.is_not(None), similarity >= similarity_threshold)
        .order_by(text("similarity_score DESC"))
        .limit(limit)
    )
    if filters:
        stmt = stmt.where(*metadata_predicates(BookModel, filters))
    if exclude_isbns:
        stmt = stmt.where(BookModel.isbn13.notin_(exclude_isbns))
    return stmt


class BookStore(BaseStore[BookModel]):
    """SQLAlchemy-based book data access layer.

    The store builds queries from a search dimension (which needs the model)
    and executes statements (which needs the session). What can be derived
    from an already-built query — counting it, materializing it, pooling
    several — lives on `DeferredBookQuery` itself.

    One exception: the embedding search is built by the module-level
    `embedding_search_stmt` instead of a method here, so a caller can record
    its SQL (`compile_sql`) before executing it — a `@task` on the store would
    mean airglider imported into `db/`, which stays free of it on purpose.
    `search_similar` is the execute half, taking the built statement the same
    way `count`/`materialize` take a `DeferredBookQuery`.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, BookModel)

    async def search_similar(self, stmt: Select) -> List[Dict[str, Any]]:
        """Run a statement built by `embedding_search_stmt` and shape the rows.

        Row shaping — not just `.scalars()` — because the statement selects the
        model plus a computed `similarity_score` column alongside it; that score
        has no home on `BookModel` and is folded into the dict here instead.
        """
        result = await self.execute_statement(stmt)
        rows = result.all()

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

    def author_query(
        self, author: str, similarity_threshold: float = 0.7
    ) -> DeferredBookQuery:
        """Build the author search without running it — same shape as
        `title_query`: isbn13 plus the fuzzy score, no ORDER BY and no LIMIT,
        so the result composes into a CTE.

        Matched as a substring rather than by equality, and scored with
        `word_similarity` rather than `similarity`, because `books.authors` is
        one semicolon-delimited credit string per book
        ("Brian Herbert;Kevin J. Anderson"). Whole-string similarity against a
        two-name credit scores a solo author low enough to lose them;
        `word_similarity` scores the name against the best-matching extent of
        the credit, so a co-credited book still surfaces on either author's
        bibliography.
        """
        stmt = select(
            self.model.isbn13,
            func.word_similarity(author, self.model.authors).label("score"),
        ).where(
            or_(
                self.model.authors.ilike(f"%{author}%"),
                func.word_similarity(author, self.model.authors)
                > similarity_threshold,
            )
        )
        return DeferredBookQuery(stmt, label="author")

    def filter_query(
        self, base: DeferredBookQuery, filters: BookMetadataFilter
    ) -> DeferredBookQuery:
        """Narrow an already-built query by metadata bounds, without running it.

        Joins the books table back onto the base query's isbn13s and ANDs the
        bounds on, so the narrowing happens in SQL over the whole upstream
        match — not over rows someone had to fetch first. Keeps the deferred
        invariants (isbn13 only, no LIMIT, no ORDER BY), so the result composes
        like any other.

        Building a query is the store's job because it needs the model; which
        bounds to apply is the filter node's. An empty filter is refused here
        rather than silently returning the base query: a no-op narrowing step
        would report a count the user reads as filtered.
        """
        predicates = metadata_predicates(self.model, filters)
        if not predicates:
            raise ValueError("Cannot filter on an empty metadata filter")

        # An anonymous subquery rather than a named CTE: two filtered queries
        # can end up composed into one statement, and two CTEs sharing a name
        # there is a compile error. The alias is generated per compile instead.
        src = base.stmt.subquery()
        columns = [self.model.isbn13]
        # a single-dimension base still carries its own score; dropping it here
        # would silently re-rank whatever materializes this by rating
        if "score" in src.c.keys():
            columns.append(src.c.score)

        stmt = (
            select(*columns)
            .join(src, self.model.isbn13 == src.c.isbn13)
            .where(*predicates)
        )
        return DeferredBookQuery(stmt, label="filtered")

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
