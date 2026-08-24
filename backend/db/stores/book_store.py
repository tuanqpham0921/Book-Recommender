from typing import List, Any, Dict

from sqlalchemy import Select, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from config import BookConstraints
from db.schema import AudienceEnum, BookMetadataFilter, BookModel, GenreEnum
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


# Rendered inline rather than passed as Python strings, which SQLAlchemy binds
# as parameters: `func.to_tsvector("english", func.coalesce(title, ""))` compiles
# to `to_tsvector(%(to_tsvector_1)s, coalesce(books.title, %(coalesce_1)s))`.
# A bind parameter inside the document expression is what stops Postgres matching
# it against `books_search_idx` — matching happens on constant-folded nodes, and
# a Param is not a Const, so a generic plan can never use the index.
_TS_CONFIG = literal_column("'english'")
_EMPTY = literal_column("''")
_SPACE = literal_column("' '")


def search_document(model: type[BookModel]):
    """The text one book is searched as: title, shelf label and blurb, as one tsvector.

    `categories` cannot answer a topic on its own — one Google-Books shelf label
    per book, 480 distinct over 5,197 rows — so "ninja", "space" and "artificial
    intelligence" all match nothing there. The blurb carries the subject. One
    document rather than three separately searched columns, so one index serves
    the whole thing.

    Pinned to the two-argument `to_tsvector(regconfig, text)`: the one-argument
    form reads `default_text_search_config` at run time and is only STABLE, so it
    cannot be indexed. `concat_ws(' ', ...)` is the obvious cleanup for the
    coalesce chain and is STABLE for the same class of reason — do not take it.

    Every `books.description` is prefixed with its own isbn13. The `english`
    parser reads that as a single `uint` lexeme rather than as digits, so no
    keyword can match it, and it only shifts positions by one, which `ts_rank`'s
    default normalization does not read. Left in rather than stripped: a
    `regexp_replace` here would double the expression that has to stay identical
    to the DDL, and the prefix belongs to ingestion anyway.

    **Duplicated as DDL in `db/schema/02_indexes.sql` and the two must stay
    character-identical** — Postgres matches an expression index structurally, so
    a changed separator here silently turns a single-digit-ms bitmap scan back
    into the 520ms sequential scan measured before the index existed.
    `tests/unit/db/stores/test_lexical_query.py` compares them.
    """
    return func.to_tsvector(
        _TS_CONFIG,
        func.coalesce(model.title, _EMPTY)
        + _SPACE
        + func.coalesce(model.categories, _EMPTY)
        + _SPACE
        + func.coalesce(model.description, _EMPTY),
    )


# The four values `books.genre` holds, indexed by the two facets that cut them.
# Set membership, never LIKE: "Nonfiction" ends in "fiction", so
# `genre ILIKE '%fiction'` matches all 5,197 rows and reports the whole catalog
# as a genre search.
_BY_GENRE = {
    GenreEnum.FICTION: ("Fiction", "Children's Fiction"),
    GenreEnum.NONFICTION: ("Nonfiction", "Children's Nonfiction"),
}
_BY_AUDIENCE = {
    AudienceEnum.CHILDREN: ("Children's Fiction", "Children's Nonfiction"),
    AudienceEnum.ADULT: ("Fiction", "Nonfiction"),
}


def genre_values(
    genre: GenreEnum | None, audience: AudienceEnum | None
) -> tuple[str, ...] | None:
    """The `books.genre` values the two facets select together, or None for neither.

    One intersected set and one `IN`, rather than two ANDed predicates: the facets
    cut the same four values on different axes, so their conjunction is an
    intersection that can be taken here — "children's fiction" is one value, not
    two predicates that happen to overlap. Every combination is non-empty, so this
    never hands back a predicate nothing can satisfy.

    `books.genre` misses two of the 449 children's books that
    `categories ILIKE 'Juvenile%'` finds (447 vs 449). Not worth a second arm.
    """
    sets = []
    if genre is not None:
        sets.append(_BY_GENRE[genre])
    if audience is not None:
        sets.append(_BY_AUDIENCE[audience])
    if not sets:
        return None

    chosen = set(sets[0])
    for other in sets[1:]:
        chosen &= set(other)
    return tuple(sorted(chosen))


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
    order (see `SimilarBooksOutput`), so it can never be a deferred query
    whose statement rides downstream on its own — recording it has to happen
    here, at the one point something still holds it unexecuted.

    Three narrowings, all optional, and all of them have to land *inside* this
    statement rather than on its result: the search orders the whole table and
    truncates at `limit`, so anything applied afterwards is applied to an
    already-capped set.

    - `similarity_threshold` is the floor. Without it this returns the top
      `limit` rows however far away they are — the whole table, ordered and
      truncated — so an ask with no near match answers with strangers.
    - `filters` are metadata bounds, and this is the only place a bound can
      reach a vector search — applied to the *result* it would cut an
      already-capped 50. No caller passes them today (`Analyze_Similar_Books`
      parses nothing), so the parameter is here for the node that re-ranks or
      picks from the pool; it is kept rather than deleted because that node
      cannot re-derive it anywhere else. An all-None filter contributes no
      predicates and is a harmless no-op, unlike `filter_query()` which refuses
      one: there narrowing is the node's whole job, so a no-op would report a
      count read as filtered.
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

    def numeric_traits_query(self, filters: BookMetadataFilter) -> DeferredBookQuery:
        """Build the metadata search over the whole catalog, without running it.

        The same predicates `filter_query` ANDs onto an upstream query, applied
        with no upstream query to AND them onto — which is what makes bounds a
        search of their own ("books under 200 pages") rather than only a
        narrowing of someone else's ("Murakami books after 2005"). Sharing
        `metadata_predicates` is what keeps the two readings of a bound from
        diverging in SQL.

        No `score` column, unlike `title_query`/`author_query`: a bound is not a
        degree of match, so there is nothing to rank by. `materialize_stmt`
        therefore falls back to `average_rating DESC`, which is the right order
        for the asks that reach here — "well rated", "most popular".

        An empty filter is refused for the same reason as in `filter_query`, and
        harder: with no base to fall back to, no predicates means selecting the
        entire catalog and reporting it as a search result.
        """
        predicates = metadata_predicates(self.model, filters)
        if not predicates:
            raise ValueError("Cannot search on an empty metadata filter")

        stmt = select(self.model.isbn13).where(*predicates)
        return DeferredBookQuery(stmt, label="numeric_traits")

    def lexical_query(
        self,
        keywords: List[str] | None = None,
        genre: GenreEnum | None = None,
        audience: AudienceEnum | None = None,
    ) -> DeferredBookQuery:
        """Build the lexical search over the whole catalog, without running it.

        Lexical, not semantic: this matches the words a book's text actually
        contains, never what it is *like*. Three facets, ANDed: what the book is
        about (full text over title, shelf label and blurb), whether it is
        fiction, and who it is for. All three in one node because they cut one
        question — "non-fiction about history" is a single search, not two to
        intersect — which is the same exception `numeric_traits_query` takes for
        bounds.

        Keywords are joined into one `plainto_tsquery`, which already ANDs the
        words it is handed: two keywords are the same query as one two-word
        keyword, and one tsquery is one index probe rather than N bitmap scans to
        AND together. Precision over recall is deliberate — "cozy mystery"
        finding one book is a better answer than "cozy OR mystery" finding two
        hundred. `plainto_tsquery` rather than `to_tsquery` for a second reason:
        it ignores punctuation in a parsed keyword instead of raising a syntax
        error on it.

        A `score` column only when there are keywords. `ts_rank` is a degree of
        match; shelf membership is not, so a genre-only search leaves
        `materialize_stmt` to fall back to `average_rating DESC` exactly as
        `numeric_traits_query` does.

        Empty args are refused for `numeric_traits_query`'s reason, and as hard:
        with no predicates this selects the entire catalog and reports it as a
        search result.
        """
        predicates = []
        columns: list = [self.model.isbn13]

        terms = " ".join(word for kw in (keywords or []) if (word := kw.strip()))
        if terms:
            document = search_document(self.model)
            tsquery = func.plainto_tsquery(_TS_CONFIG, terms)
            predicates.append(document.op("@@")(tsquery))
            columns.append(func.ts_rank(document, tsquery).label("score"))

        values = genre_values(genre, audience)
        if values:
            predicates.append(self.model.genre.in_(values))

        if not predicates:
            raise ValueError("Cannot search on an empty lexical filter")

        stmt = select(*columns).where(*predicates)
        return DeferredBookQuery(stmt, label="lexical")

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
        # annotated because the list is heterogeneous: an ORM column, then the
        # subquery's `score`, which pyright sees as a KeyedColumnElement
        columns: list = [self.model.isbn13]
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
