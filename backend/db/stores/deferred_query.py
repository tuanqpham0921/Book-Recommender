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
    knows what the vector was made from: the recommend node labels it
    `embed(search_text)`, naming a value its own record already holds twice
    (the task's `input.search_text`, and `RecommendationOutput.search_text`),
    so the statement stays reproducible without carrying a third copy.

    The default fires on no statement built today — no deferred query carries a
    vector — and is here so one that starts to cannot silently write 43KB into
    `chat_runs`.
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
        passes through untouched and keeps its score.
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
        """COUNT over this query without materializing its rows."""
        return select(func.count()).select_from(self.cte("matched"))

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
