"""The generation stage's flow. `run` is the table of contents; everything else
sits where the flow reaches it.

Same reading rule as a slice (domains/README.md): this file is the flow —
`run()` plus every step, in the order `run` reaches them — and `render.py` is
the one LLM call's pure half.

**Not a node** (2026-09-08). It was `Generate_Recommendations`, a registered
`NodeTier.GENERATE` slice the planner ended a recommendation chain with; it is
now one unregistered stage the orchestrator runs once, after the task runner,
over everything the plan produced. That is the sink-shaped alternative in
docs/design/execution-pipeline-v1.md, collapsed to a single sink per turn.
Three things follow from it and are why the code below looks the way it does:

- There is no goal, so no planner brief. The user's own message is the brief,
  read off `ctx.user_message` — legitimate here in a way it never was for a
  node, because this is the only stage that answers the *turn*.
- There is no `depends_on`, so nothing pre-selects what it writes about. It
  partitions the whole results map itself, in `_partition`.
- It is planned for every turn, so it can no longer be scoped to
  recommendation asks. A plain lookup now gets prose too, which closes the gap
  named in CLAUDE.md — and costs the golden check that a *planned* generation
  goal gave, since a stage that always runs can never be missing from a plan.

It is still terminal, so it is the place rows are materialized to be kept:
counts-first means every node upstream handed on a `DeferredBookQuery` and
nothing else fetched. That is why it subclasses `BookReaderWorkflow` — it reads
and shows books while producing prose rather than a count.
"""

from app.domains.base_workflow import FailedGoalOutput, NodeWorkflowOutput
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

# How many sources get a round trip. This used to see only one chain's goals
# and the cap rarely bit; it now sees the whole plan, so it is the thing that
# stops a wide compound turn ("books by King, by Austen, under 200 pages, …")
# turning one reply into a dozen materializations. Sources are in execution
# order, so what a cap drops is the tail the planner listed last.
MAX_MATERIALIZED_SOURCES = 4

# Cards land one at a time here, unlike a preview's instant dump: these are the
# recommendations, and the arrival is part of reading them.
CARD_DELAY = 0.03


class GenerateRecommendationsExecutor(BookReaderWorkflow[RecommendationsOutput]):
    ui_loading_message = "Writing recommendations..."
    ui_section_title = "Recommendations"
    # the reply is the point of the turn — never folded away
    ui_section_collapsible = False

    async def run(self, node_input: RecommendationsInput) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        sources, failures = self._partition(node_input.results)
        # The orchestrator does not run this stage over an empty results map,
        # so reaching here with nothing is a caller bug rather than a plan that
        # went badly — raising surfaces it as this stage's failure instead of
        # an empty reply.
        if not sources and not failures:
            raise ValueError("Nothing to write from: the plan produced no results")

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
            await self.write_recommendations(sources, rows, failures)
        ).unwrap()

        # 4. last: ok is read off the output
        self.finalize_result()

    def _partition(
        self, results: list[NodeWorkflowOutput]
    ) -> tuple[list[BookRetrievalOutput], list[FailedGoalOutput]]:
        """The run split into what produced books and what did not.

        What `build_input` used to do from the planner's `depends_on`, done
        here from the whole map instead — the same `isinstance` matching, just
        no longer able to miss a goal because nothing declared a dependency on
        it. That is the actual behaviour change of deregistering: a title
        lookup running alongside a recommendation chain used to be invisible to
        the reply unless the planner wired it in, and is now always in scope.

        A third case is possible and deliberately dropped rather than guessed
        at: an output that is neither book-shaped nor a failure. Nothing
        registered produces one today, so it is logged as a detail rather than
        given a rendering nobody can check.
        """
        sources: list[BookRetrievalOutput] = []
        failures: list[FailedGoalOutput] = []

        for output in results:
            if isinstance(output, FailedGoalOutput):
                failures.append(output)
            elif isinstance(output, BookRetrievalOutput):
                sources.append(output)
            else:
                self.add_details(f"nothing to write from a {type(output).__name__}")

        return sources, failures

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
        self,
        sources: list[BookRetrievalOutput],
        rows: list[list[Book]],
        failures: list[FailedGoalOutput],
    ) -> str | None:
        """The reply, streamed to the browser as it is written.

        A `@task` so the call's spend and duration are attributed to the
        writing rather than to the fetches before it. Not a `Workflow`: the
        payload is a string, with no declared output type to carry.

        None when the model returned nothing at all, which `run` lets reach
        `finalize_result` as a failed claim — a turn that got as far as here
        and produced no words has not been answered.
        """
        rendered = render_report(sources, rows, failures)
        self.add_details(
            f"writing from {len(sources)} source(s), {len(failures)} failure(s)"
        )

        req = build_recommendations_request(
            rendered, self.sse_stream, self.user_message.content
        )
        
        # TODO: add the assistant message into here
        from clients.messages import AssistantMessage
        self.messages.append(AssistantMessage(content=rendered))
        
        message = await self.run_llm_call(req)
        return message.content

    def finalize_result(self) -> None:
        """ok means the turn was reported on, not that books were found.

        A reply over empty sources — or over nothing but failures — is a
        correct answer: "I don't have that, so I couldn't look for anything
        like it" is the reply, and marking it failed would surface the generic
        error message instead and tell the user nothing.
        """
        super().finalize_result(ok=bool(self.result.text))
