"""The intersect node's flow — the single-call shape with the call removed.

Four files like `find_by_title/`, minus the parse: this node reads nothing out
of its goal text, so there is no `*Args` schema, no `build_arg_parser_request`
and no `args` field. It is the one node in the app that makes no LLM call at
all — what it does is decided entirely by which goals it depends on, which is
`build_input`'s job rather than a parse's.

What is left is the counts-first move over a composed query: read the upstream
queries, AND them, count, preview, finalize. Reading them stays a module-level
function here rather than a `dependents.py`: there is one thing to pull out of
an anchor, which has not outgrown `run`.
"""

from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.external import BookRetrievalOutput
from db.stores import DeferredBookQuery

from .external import CombineIntersectInput, CombineIntersectOutput


def anchor_queries(anchors: list[BookRetrievalOutput]) -> list[DeferredBookQuery]:
    """The queries this node can intersect, out of what its dependencies produced.

    Every registered retrieval fills `query`, so the dropped branch catches a
    malformed upstream output rather than a shape this node is expected to
    handle — `run` says so when too few survive. The optional field is read
    honestly all the same, because "counted nothing" and "counted but handed on
    no query" are different failures and only the second is a bug.
    """
    return [anchor.query for anchor in anchors if anchor.query is not None]


class CombineIntersectExecutor(BookWorkflow[CombineIntersectOutput]):
    ui_loading_message = "Narrowing the results..."
    ui_section_title = "Books matching every condition"

    async def run(self, node_input: CombineIntersectInput) -> None:
        """AND the upstream queries in SQL and hand the intersection on.

        Intersecting the queries rather than fetched lists is what keeps the
        count honest: it is over every upstream match, not over the handful of
        rows each preview happened to show. It is also what lets a similarity
        pool keep its cosine ranking through the narrowing — `compose` carries
        the one score through an `"and"`, and `materialize_stmt` orders by it.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. what this node was given — selection was the input contract's job,
        # interpreting it is this node's
        upstream = anchor_queries(node_input.anchors)
        # the upstream counts, read off the outputs rather than re-counted
        self.add_details(
            " ∩ ".join(str(anchor.num_books) for anchor in node_input.anchors)
        )
        if len(upstream) < 2:
            raise ValueError(
                f"Nothing to intersect: {len(upstream)} of "
                f"{len(node_input.anchors)} results carry a query. Every "
                "registered retrieval hands one on, so this is a malformed "
                "upstream output rather than a plan this node can be asked to fix"
            )

        # 2. AND them — still no rows: the intersection is what the count runs
        # over, and what travels downstream
        deferred = DeferredBookQuery.compose(upstream, op="and", label="intersected")
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(
            f"- {total} books match all {len(upstream)} conditions"
        )

        # 3. Cards for the section, kept on the output as `preview` for the
        # record and the reply — what travels downstream is the intersected
        # query on `self.result`. Skipped entirely when nothing satisfied every
        # condition.
        if total:
            self.result.preview = (await self.fetch_books(deferred)).unwrap()
            await self.stream_books(self.result.preview)

        # 4. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the conditions were ANDed and counted", not "something
        # survived them" — an empty intersection is an answer this node reports,
        # and it is how the user learns which condition to drop. There is no
        # `args` half to the claim: this node parses nothing.
        ok = self.result.query is not None
        return super().finalize_result(ok=ok)
