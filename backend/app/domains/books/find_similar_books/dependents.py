"""Interpret what this node's dependencies handed it — step 1 of the flow.

`SimilarBooksInput.anchors` already did *selection* (by type, in `build_input`);
this is the *interpretation* half the input contract deliberately leaves to the
executor (domains/README.md, executor rule 4): sorting each anchor by what the
node can do with it — rows, or the query that would fetch them — and totalling
how many books that comes to. Nothing here renders prompts or touches the LLM;
that starts in `analyze_references.py`, which reads this module's output.

The total is the reason this module still earns its place. Every anchor counted
itself before handing on its query, so the size of the pooled anchor is knowable
without a round trip — which is what let `fetch_anchor_books`' count-then-cap
step disappear from `BookWorkflow`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domains.books.external import BookAnchorOutput, BookRetrievalOutput
from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery


@dataclass
class ParsedDependents:
    """The node's anchors sorted by what it can do with each one.

    `SimilarBooksInput.anchors` already selected them, so everything arriving
    here is a book-producing output. What is left is the real choice: rows if a
    dependency has them, otherwise the query that would produce them.

    The book-shaped branch is gated on `isinstance(BookRetrievalOutput)` rather
    than on a `getattr` for `query`: that is the base of the type
    `SimilarBooksInput.anchors` declares, and it is what makes `num_books` safe
    to read below — a count only means something on an output that promises one.

    *Within* that branch `books` stays duck-typed, and deliberately. Declaring
    rows is a shape claim, not a class, and no registered node makes it on an
    anchor today — `SimilarBooksOutput` is a candidate, so it cannot arrive
    here. Two things keep the pile: a test can hand this node reference books
    with no database at all, and the next anchor that carries rows rather than a
    query lands here without this file learning its name.
    """

    # TODO: have a rejected or .ok = False
    # this is for the dependents results
    # so you don't have to run this if all the dependents have no output
    # if there are stuff like similar_to(brave new world, dune)
    # you can still generate, since I didn't find brave new world, I can only
    # here are some books similar to Dune...

    # what to fetch rows from — the anchor for the similarity search, and the
    # usual case now that retrieval nodes hand on a query rather than rows
    queries: list[DeferredBookQuery] = field(default_factory=list)
    # rows a dependency already chose, used as-is
    books: list[Book] = field(default_factory=list)
    # How many books the pooled queries reach, summed off the anchors' own
    # counts. Free — each one already ran a COUNT — and it is what `total()`
    # checks the anchor cap against before a single row is fetched. An upper
    # bound when two title searches overlap, which errs toward folding fewer
    # books rather than more.
    num_matched: int = 0
    # Class names of book-shaped anchors that matched nothing. A retrieval
    # stamps its query whether or not it matched, so `num_books == 0` is the
    # only thing separating "here is how to reach them" from "there were none"
    # — and an empty query composed into the anchor is an OR branch that
    # contributes no rows and costs a scan. Kept rather than dropped because
    # the difference between "the planner sent no anchor" and "every lookup
    # came back empty" is the first question asked when this node refuses.
    empty: list[str] = field(default_factory=list)
    # Class names of anything this node can't read at all — an anchor that is
    # not book-shaped, or one with neither rows nor a query. The input contract
    # makes the first unreachable in production; the pile is what a malformed
    # output lands in instead of being silently skipped.
    #
    # The class name is all there is to say: outputs no longer carry the id of
    # the goal that produced them, and only the task runner's `results` map
    # knows which was which.
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def from_anchors(
        cls, anchors: Sequence[BookAnchorOutput]
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
                        parsed.num_matched += result.num_books
                    else:
                        parsed.empty.append(type(result).__name__)
                    claimed = True

            if not claimed:
                parsed.unknown.append(type(result).__name__)

        return parsed

    def total(self) -> int:
        """How many books the anchor comes to, before any of them are fetched.

        Both piles count: rows a dependency already chose are as much a part of
        the anchor as rows this node is about to fetch. This is what
        `check_anchors` reads — the cap is about how many books get folded into
        one description, not about where they came from.
        """
        return self.num_matched + len(self.books)

    def is_empty(self) -> bool:
        """Nothing to be similar *to*. The caller raises on this rather than
        recovering: an anchor that matched nothing and no anchor at all are
        both plans that cannot produce what this node claims, and there is no
        goal text left to fall back on. `empty` and `unknown` say which of the
        two it was."""
        return not self.total()

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_queries": len(self.queries),
            "num_books": len(self.books),
            "total": self.total(),
            "empty": self.empty,
            "unknown": self.unknown,
        }
