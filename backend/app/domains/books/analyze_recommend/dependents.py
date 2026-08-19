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

from app.domains.books.external import BookRetrievalOutput
from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery


@dataclass
class ParsedDependents:
    """The node's anchors sorted by what it can do with each one.

    `RecommendInput.anchors` already selected them, so everything arriving here
    is a book-producing output. What is left is the real choice: rows if a
    dependency has them, otherwise the query that would produce them.

    The book-shaped branch is gated on `isinstance(BookRetrievalOutput)` rather
    than on a `getattr` for `query`: that is the type `RecommendInput.anchors`
    already declares, and it is what makes `num_books` safe to read below — a
    count only means something on an output that promises one.

    *Within* that branch `books` stays duck-typed, and deliberately: declaring
    rows is a shape claim, not a class. `RecommendationOutput` is the only node
    making it today, but the next node that chooses rows should land here
    without this file learning its name.

    `reports` is duck-typed for the same reason and a stronger one —
    `AnalyzeBooksOutput` is a reserved name with no class yet, so there is
    nothing to isinstance against. This is the seam for the first node that
    produces one.
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
    # Class names of book-shaped anchors that matched nothing. A retrieval
    # stamps its query whether or not it matched, so `num_books == 0` is the
    # only thing separating "here is how to reach them" from "there were none"
    # — and an empty query composed into the anchor is an OR branch that
    # contributes no rows and costs a scan. Kept rather than dropped because
    # the difference between "the planner sent no anchor" and "every lookup
    # came back empty" is the first question asked when this node refuses.
    empty: list[str] = field(default_factory=list)
    # Class names of anything this node can't read at all — an anchor that is
    # not book-shaped and carries no report. A routing mistake, unlike `empty`.
    #
    # The class name is all there is to say: outputs no longer carry the id of
    # the goal that produced them, and only the task runner's `results` map
    # knows which was which.
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def from_anchors(
        cls, anchors: Sequence[BookRetrievalOutput]
    ) -> "ParsedDependents":
        parsed = cls()
        for result in anchors:
            claimed = False

            if isinstance(result, BookRetrievalOutput):
                # Rows, or the query that would produce them — never both, and
                # never both on the same class either: rows mean a node that
                # chose them, a query means a retrieval that counted and
                # stopped. The `elif` is the belt to that braces, so an output
                # growing both cannot weight its set twice in the anchor.
                books = getattr(result, "books", None)
                if books:
                    parsed.books.extend(books)
                    claimed = True
                elif result.query is not None:
                    # a query that counted 0 reaches no rows; pooling it would
                    # add an empty branch to the anchor's OR and hide, behind a
                    # non-empty `queries`, that nothing was found
                    if result.num_books:
                        parsed.queries.append(result.query)
                    else:
                        parsed.empty.append(type(result).__name__)
                    claimed = True

            report = getattr(result, "report", None)
            if report:
                parsed.reports.append(report)
                claimed = True

            if not claimed:
                parsed.unknown.append(type(result).__name__)

        return parsed

    def is_empty(self) -> bool:
        """Nothing to be similar *to*. The caller raises on this rather than
        recovering: an anchor that matched nothing and no anchor at all are
        both plans that cannot produce what this node claims, and falling back
        on the goal text would answer a different question than was asked.
        `empty` and `unknown` say which of the two it was."""
        return not (self.queries or self.books or self.reports)

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_queries": len(self.queries),
            "num_books": len(self.books),
            "num_reports": len(self.reports),
            "empty": self.empty,
            "unknown": self.unknown,
        }
