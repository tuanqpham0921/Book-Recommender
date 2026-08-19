from typing import List, Any, Dict

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
        filters: BookMetadataFilter | None = None,
        exclude_isbns: List[str] | None = None,
        similarity_threshold: float = BookConstraints.MIN_SIMILARITY,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """The books nearest an embedding, narrowed to those worth ranking.

        This is not a deferred query and cannot be one: it returns rows in
        cosine order, and that order is the point — no `DeferredBookQuery`
        reproduces it (see `RecommendationOutput`). So everything that would
        otherwise narrow it downstream has to narrow it *here*, before the
        `limit` truncates, or the cut lands on an already-capped 50.

        Three narrowings, all optional:

        - `similarity_threshold` is the floor. Without it this returns the top
          `limit` rows however far away they are — the whole table, ordered and
          truncated — so an ask with no near match answers with strangers.
        - `filters` are the metadata bounds the recommend node parsed. An
          all-None filter contributes no predicates and is a harmless no-op,
          unlike `filter_query()` which refuses one: there narrowing is the
          node's whole job, so a no-op would report a count read as filtered.
        - `exclude_isbns` drops the books the ask already named. In SQL rather
          than in the caller, so the excluded rows do not eat `limit` slots.
        """
        embed_col = self.model.embedding
        # cosine similarity = 1 - cosine distance
        similarity = 1 - embed_col.cosine_distance(query_embedding)
        stmt = (
            select(self.model, similarity.label("similarity_score"))
            # .where(embed_col.is_not(None), similarity >= similarity_threshold)
            .order_by(text("similarity_score DESC"))
            .limit(limit)
        )
        if filters:
            stmt = stmt.where(*metadata_predicates(self.model, filters))
        if exclude_isbns:
            stmt = stmt.where(self.model.isbn13.notin_(exclude_isbns))

        # from db.stores.deferred_query import compile_sql
        # print(compile_sql(stmt))
        
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
