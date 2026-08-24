"""A book query that has been built but not executed for rows.

Retrieval nodes hand one of these downstream instead of a book list: the node
runs only a COUNT, and whichever node is last in the plan turns the query into
rows. See docs/design/execution-pipeline-v1.md.

Everything that can be *derived* from a built query lives here as a method —
the counting statement, the materializing statement, pooling several into one —
so the store's job is reduced to the two things a derivation can't do: build a
query from a search dimension (that needs the model) and execute a statement
(that needs the session).
"""

import re
from typing import List

from sqlalchemy import Select, func, intersect, select, union
from sqlalchemy.orm import defer

# A pgvector literal renders as every float in the vector: 43KB for the 1024
# dims this catalog uses, against ~580 for the rest of the statement. Nothing
# reads it, and dropping `literal_binds` to avoid it would take the bounds and
# the isbn13s with it — those are the reason the SQL is rendered at all.
#
# 120 chars of digits and commas is far above any hand-written list literal and
# far below a real vector, so this matches the vector and only the vector.
_VECTOR_LITERAL = re.compile(r"'\[[-0-9.,e+ ]{120,}\]'")


def compile_sql(stmt, embedding_as: str = "embedding") -> str:
    """Compile a SQLAlchemy statement to a readable SQL string.

    Any vector literal collapses to `embedding_as`, because only the caller
    knows what the vector was made from: the similarity node labels it
    `embed(search_text)`, naming a value its own record already holds twice
    (the task's `input.search_text`, and `SimilarBooksOutput.search_text`),
    so the statement stays reproducible without carrying a third copy.

    One deferred query does carry a vector — `embedding_search_stmt`'s — so the
    default is a live fallback rather than a guard against a hypothetical: a
    caller that forgets the label still gets `embedding` rather than 43KB of
    floats in `chat_runs`. It only loses the label, not the elision.
    """
    try:
        compiled = stmt.compile(
            compile_kwargs={"literal_binds": True, "render_postcompile": True}
        )
        sql = str(compiled)
    except Exception:
        # fallback without literal binds
        sql = str(stmt.compile())
    return _VECTOR_LITERAL.sub(embedding_as, sql)


class DeferredBookQuery:
    """Wraps a SELECT of isbn13 (plus an optional `score` column).

    Two invariants are what make these composable into a single WITH clause:
    **no LIMIT and no ORDER BY**. Both belong to the step that materializes,
    because a limit applied per-dimension would silently shrink whatever a
    later composition can find.

    **One query takes a documented exception**: the vector search
    (`embedding_search_stmt`). It does not select a subset — it orders the
    whole table by cosine distance and truncates — so its LIMIT is not a shrunk
    view of a set, it *is* the set. `materialize_stmt` can reproduce a ranking
    (it orders by `score`), but not a ranking-truncation, so the truncation has
    to happen where the ranking does. Everything else still holds for it:
    isbn13 plus a `score`, so `filter_query` narrows it and keeps cosine order,
    and `count_stmt`/`materialize_stmt` work unchanged.

    **Nothing on this class marks that exception, and `compose()` does not
    refuse it.** A tracked `capped` attribute and a guard on composition were
    both tried and removed on 2026-08-24: pooling the vector query with an
    uncapped one *is* lossy in ways the composed result cannot show, but no
    registered plan reaches it — the combine tier has no members, and
    `Filter_Retrieval` is parked and single-input — so the machinery guarded a
    caller that does not exist. The reasoning is kept in
    docs/design/execution-pipeline-v1.md rather than in code. If such a caller
    appears, the better fix is a similarity floor tuned to bound the pool
    without a LIMIT, which removes the exception instead of policing it.

    Deliberately not a Pydantic model or a dataclass: it rides on a Pydantic
    output field, and nothing should try to walk into `stmt`.
    """

    __slots__ = ("stmt", "label")

    def __init__(self, stmt: Select, label: str = "q"):
        self.stmt = stmt
        self.label = label

    def cte(self, name: str | None = None):
        """CTE names must be unique across a composed tree — `compose()` names
        its inputs positionally rather than trusting `label` to be distinct."""
        return self.stmt.cte(name=name or self.label)

    @classmethod
    def compose(
        cls, queries: List["DeferredBookQuery"], op: str = "or", label: str = "combined"
    ) -> "DeferredBookQuery":
        """Pool deferred queries into one, via a WITH clause.

        `"or"` pools (the implicit-union rule), `"and"` intersects; Postgres
        dedups by isbn13 either way. Only isbn13 survives — a per-dimension
        `score` means nothing once two dimensions combine — so a single input
        passes through untouched and keeps its score. That passthrough is what
        `Filter_Retrieval` rides on: it pools its dependencies unconditionally,
        and the common case is one.

        **Composing the vector query is lossy and nothing here stops it.** Its
        LIMIT is applied before the union or intersect, so it changes which
        books qualify rather than only how many are shown, and dropping `score`
        then removes the ranking that chose them. Left unguarded deliberately —
        no registered plan composes one today. See the class docstring.
        """
        if not queries:
            raise ValueError("compose() needs at least one query")
        if len(queries) == 1:
            return cls(queries[0].stmt, label=label)

        # positional names, because two nodes can legitimately carry the same label
        parts = [select(q.cte(f"q{i}").c.isbn13) for i, q in enumerate(queries)]
        combined = (union if op == "or" else intersect)(*parts).cte(label)
        return cls(select(combined.c.isbn13), label=label)

    def count_stmt(self):
        """COUNT over this query without materializing its rows.

        On the vector query this returns `min(limit, matches)` and so says
        little on its own — `score_stats_stmt()` is what describes that pool.
        """
        return select(func.count()).select_from(self.cte("matched"))

    def score_stats_stmt(self):
        """Count plus the spread of `score`, in one row — or None with no score.

        The counting statement for a query whose count is degenerate. The
        vector search always reports its LIMIT, so what tells you whether the
        pool is any good is how far the scores fall across it: a `min` sitting
        on the similarity floor means the cap is doing the work and the floor
        is not, which is the measurement `BookConstraints.MIN_SIMILARITY` has
        never had.

        Derived from the built query rather than executed here, like every
        other statement on this class. None rather than zeroes when there is no
        `score` column, because "these books have no degree of match" and
        "their scores are all 0.0" are different facts and a caller must not
        read the second for the first.
        """
        src = self.cte("scored")
        if "score" not in src.c.keys():
            return None

        return select(
            func.count().label("count"),
            func.min(src.c.score).label("min"),
            func.max(src.c.score).label("max"),
            func.avg(src.c.score).label("avg"),
        ).select_from(src)

    def materialize_stmt(self, model, limit: int = 10):
        """The one statement that returns books: join this query's isbn13s back
        to the books table. Ranks by the query's own `score` when it still has
        one, by rating otherwise — a composition leaves no score to rank on.
        """
        src = self.cte("final")
        stmt = select(model).join(src, model.isbn13 == src.c.isbn13)
        # ~6KB a row and nothing downstream reads it; raiseload makes an
        # accidental access a clear error rather than a lazy load that
        # deadlocks under asyncio
        stmt = stmt.options(defer(model.embedding, raiseload=True))
        if "score" in src.c.keys():
            stmt = stmt.order_by(src.c.score.desc())
        else:
            stmt = stmt.order_by(model.average_rating.desc().nulls_last())
        return stmt.limit(limit)

    def __repr__(self) -> str:
        return f"<DeferredBookQuery {self.label}>"
