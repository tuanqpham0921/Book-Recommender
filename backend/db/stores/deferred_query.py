"""A book query that has been built but not executed for rows.

Retrieval nodes hand one of these downstream instead of a book list: the node
runs only a COUNT, and whichever node is last in the plan turns the query into
rows. See docs/design/execution-pipeline-v1.md.
"""

from sqlalchemy import Select


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

    def __repr__(self) -> str:
        return f"<DeferredBookQuery {self.label}>"
