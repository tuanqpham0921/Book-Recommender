"""The generation node's flow. `run` is the table of contents; everything else
sits where the flow reaches it.

Same reading rule as the other slices (domains/README.md): this file is the flow
— `run()` plus every step, in the order `run` reaches them — and `render.py` is
the one LLM call's pure half.

This is the first slice in `NodeTier.GENERATE`: a registered node the planner
ends every recommendation chain with, unlike the sink-attached answer stage on
the `generation_node_sink` branch (see docs/design/execution-pipeline-v1.md for
the comparison). Being a goal is what lets the description say *what to write*
("…and explain why each fits") and what lets QA/compare/general generation
arrive later as sibling slices rather than branches of one prompt.

It is also a terminal node, so it is the place rows are materialized to be
kept: counts-first means every node upstream handed on a `DeferredBookQuery`
and nothing else fetched. That is why it subclasses `BookReaderWorkflow` — it
reads and shows books while producing prose rather than a count.
"""

from app.domains.books.base_workflow import BookReaderWorkflow
from app.domains.books.external import BookRetrievalOutput
from app.domains.books.schemas import Book
from airglider import task

from .external import RecommendationsInput, RecommendationsOutput
from .render import build_recommendations_request, render_report

# Rows fetched per source. Larger than `BookConstraints.default_limit` (3),
# which sizes a preview in a section nobody expands — these are the cards the
# reply is actually about, and the writer needs enough of them to say something
# true about the set rather than about three arbitrary members of it.
ROWS_PER_SOURCE = 5

# How many sources get a round trip. A recommendation chain usually feeds this
# node one goal, so the cap only bites on a wide compound plan — where it stops
# one reply turning into a dozen materializations. Sources are fetched in plan
# order, so what a cap drops is the tail the planner listed last.
MAX_MATERIALIZED_SOURCES = 4

# Cards land one at a time here, unlike a preview's instant dump: these are the
# recommendations, and the arrival is part of reading them.
CARD_DELAY = 0.03


class GenerateRecommendationsExecutor(BookReaderWorkflow[RecommendationsOutput]):
    ui_loading_message = "Writing recommendations..."
    ui_section_title = "Recommendations"
    # the reply is the point of the chain — never folded away
    ui_section_collapsible = False

    async def run(self, node_input: RecommendationsInput) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        sources, failures = node_input.sources, node_input.failures
        # Both defaulted so a failed branch still reaches this node; both empty
        # means a generation goal depending on nothing, which is a plan bug —
        # raising surfaces it as this goal's failure instead of an empty reply.
        if not sources and not failures:
            raise ValueError(
                "Nothing to recommend from: no goal fed this one books or a failure"
            )

        # 1. materialize. The one place in the app rows are fetched to be kept:
        # every source counted and handed on its query, and `materialize_stmt`
        # orders by `score`, so a similarity pool arrives cosine-first.
        rows = (await self.materialize(sources)).unwrap()

        # 2. cards, before the prose. One `stream_books` call rather than one
        # per source, because its isbn13 dedup is per call — two sources that
        # both matched Dune must not show Dune twice.
        shown = [book for books in rows for book in books]
        await self.stream_books(shown, delay=CARD_DELAY)
        self.result.num_books_shown = len(shown)

        # 3. the reply. It reaches the browser from inside this call — the
        # request carries the SSE stream and the client pushes each delta — so
        # what comes back is for the record, not for sending.
        self.result.text = (
            await self.write_recommendations(node_input, rows)
        ).unwrap()

        # 4. last: ok is read off the output
        self.finalize_result()

    @task
    async def materialize(
        self, sources: list[BookRetrievalOutput]
    ) -> list[list[Book]]:
        """Rows for each source, positional against `sources`.

        Empty lists for the sources that have nothing to fetch — one that
        matched nothing, one with no query, one past the cap — so the renderer
        can zip the two lists and still tell those cases apart from each
        source's own `num_books`.
        """
        rows: dict[int, list[Book]] = {}
        budget = MAX_MATERIALIZED_SOURCES

        for index, source in enumerate(sources):
            if not source.num_books:
                continue
            if source.query is None:
                # every registered node fills `query`; a mock or a future node
                # that does not is a source the reply can still count, not fetch
                self.add_details(f"source {index + 1} has a count but no query")
                continue
            if not budget:
                self.add_details(f"source {index + 1} not materialized (cap reached)")
                continue

            budget -= 1
            fetched = await self.fetch_books(source.query, ROWS_PER_SOURCE)
            rows[index] = fetched.unwrap()

        return [rows.get(index, []) for index in range(len(sources))]

    @task
    async def write_recommendations(
        self, node_input: RecommendationsInput, rows: list[list[Book]]
    ) -> str | None:
        """The reply, streamed to the browser as it is written.

        A `@task` so the call's spend and duration are attributed to the
        writing rather than to the fetches before it. Not a `Workflow`: the
        payload is a string, with no declared output type to carry.

        None when the model returned nothing at all, which `run` lets reach
        `finalize_result` as a failed claim — a chain that got as far as here
        and produced no words has not been answered.
        """
        rendered = render_report(node_input.sources, rows, node_input.failures)
        self.add_details(
            f"writing from {len(node_input.sources)} source(s), "
            f"{len(node_input.failures)} failure(s)"
        )

        req = build_recommendations_request(
            rendered, self.sse_stream, self.user_message.content
        )
        message = await self.run_llm_call(req)
        return message.content

    def finalize_result(self) -> None:
        """ok means the chain was reported on, not that books were found.

        A reply over empty sources — or over nothing but failures — is a
        correct answer: "I don't have that, so I couldn't look for anything
        like it" is the reply, and marking it failed would surface the generic
        error message instead and tell the user nothing.
        """
        super().finalize_result(ok=bool(self.result.text))
