"""Interpret what this node's dependencies handed it — step 1 of the flow.

`RecommendInput.anchors` already did *selection* (by type, in `build_input`);
this is the *interpretation* half the input contract deliberately leaves to the
executor (domains/README.md, executor rule 4): sorting each anchor by what the
node can do with it — rows, or the query that would fetch them, or a written
report. Nothing here renders prompts or touches the LLM; that starts in
`analyze_references.py`, which reads this module's output.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery


@dataclass
class ParsedDependents:
    """The node's anchors sorted by what it can do with each one.

    `RecommendInput.anchors` already selected them, so everything arriving here
    is a book-producing output. What is left is the real choice: rows if a
    dependency has them, otherwise the query that would produce them.

    Read by duck typing throughout: an anchor is whatever a dependency
    produced, and this class asks it what it has rather than what it is.

    Which branch an anchor takes is now structural rather than a guess:
    `BookRetrievalOutput` carries a query and no rows, and only a node that
    *chose* rows (`RecommendationOutput`) declares `books`. So a retrieval
    anchor lands in `queries` because it has nothing else to land as.

    `reports` is read by duck typing — `AnalyzeBooksOutput` is a reserved name
    with no class yet. This is the seam for the first node that produces one.
    """

    # TODO: have a rejected or .ok = False
    # this is for the dependents results
    # so you don't have to run this if all the dependents have no output
    # if there are stuff like recommend(brave new world, dune)
    # you can still generate, since I didn't find brave new world, I can only
    # here are some books similar to Dune...

    # what to fetch rows from — the anchor for the similarity search, and the
    # usual case now that retrieval nodes hand on a query rather than rows
    queries: list[DeferredBookQuery] = field(default_factory=list)
    # rows a dependency already chose (RecommendationOutput), used as-is
    books: list[Book] = field(default_factory=list)
    # written reports about books (AnalyzeBooksOutput, reserved)
    reports: list[str] = field(default_factory=list)
    # Class names of anything this node can't read — an anchor carrying neither
    # rows nor a query, which now means an output that is not book-shaped rather
    # than one that found nothing: a retrieval stamps its query whether or not it
    # matched. A real state to report, not a routing mistake.
    #
    # The class name is all there is to say: outputs no longer carry the id of
    # the goal that produced them, and only the task runner's `results` map
    # knows which was which.
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def from_anchors(cls, anchors: Sequence[Any]) -> "ParsedDependents":
        parsed = cls()
        for result in anchors:
            claimed = False

            # Rows, or the query that would produce them — never both, and now
            # never both on the same class either: rows mean a node that chose
            # them, a query means a retrieval that counted and stopped. The
            # `elif` is the belt to that braces, so an output growing both
            # cannot weight its set twice in the anchor.
            books = getattr(result, "books", None)
            query = getattr(result, "query", None)

            if books:
                parsed.books.extend(books)
                claimed = True
            elif query is not None:
                parsed.queries.append(query)
                claimed = True

            report = getattr(result, "report", None)
            if report:
                parsed.reports.append(report)
                claimed = True

            if not claimed:
                parsed.unknown.append(type(result).__name__)

        return parsed

    def is_empty(self) -> bool:
        """No usable anchor. The node has nothing to be similar *to* and has to
        fall back on the user's own words."""
        return not (self.queries or self.books or self.reports)

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_queries": len(self.queries),
            "num_books": len(self.books),
            "num_reports": len(self.reports),
            "unknown": self.unknown,
        }
