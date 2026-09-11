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

**It no longer fetches** (2026-09-11). Every book node keeps the preview it
streamed on its output, and the runner hands each goal on as a `TaskResult` —
the output plus a summary of what it cost — so the rows the reply names were
fetched where each goal ran. The round trips this stage used to spend are gone,
and with them their cap, which dropped the *last* sources in execution order —
the final answers first. It still subclasses `BookReaderWorkflow`, for
`stream_books`.
"""

from app.domains.base_workflow import FailedGoalOutput
from app.domains.books.base_workflow import BookReaderWorkflow
from app.domains.books.external import BookRetrievalOutput
from app.orchestration.task_runner import TaskResult
from airglider import task

from .external import RecommendationsInput, RecommendationsOutput
from .render import build_recommendations_request, render_report

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

        # 1. cards, before the prose. One `stream_books` call rather than one
        # per source, because its isbn13 dedup is per call — two sources that
        # both matched Dune must not show Dune twice.
        shown = [book for result in sources for book in result.output.preview]
        await self.stream_books(shown, delay=CARD_DELAY)
        self.result.num_books_shown = len(shown)

        # 2. the reply. It reaches the browser from inside this call — the
        # request carries the SSE stream and the client pushes each delta — so
        # what comes back is for the record, not for sending.
        self.result.text = (
            await self.write_recommendations(sources, failures)
        ).unwrap()

        # 3. last: ok is read off the output
        self.finalize_result()

    def _partition(
        self, results: list[TaskResult]
    ) -> tuple[list[TaskResult], list[TaskResult]]:
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
        sources: list[TaskResult] = []
        failures: list[TaskResult] = []

        for result in results:
            if isinstance(result.output, FailedGoalOutput):
                failures.append(result)
            elif isinstance(result.output, BookRetrievalOutput):
                sources.append(result)
            else:
                self.add_details(
                    f"nothing to write from a {type(result.output).__name__}"
                )

        return sources, failures

    @task
    async def write_recommendations(
        self,
        sources: list[TaskResult],
        failures: list[TaskResult],
    ) -> str | None:
        """The reply, streamed to the browser as it is written.

        A `@task` so the call's spend and duration are attributed to the
        writing rather than to the cards before it. Not a `Workflow`: the
        payload is a string, with no declared output type to carry.

        Sources first, then failures, so the report reads what was found
        before what could not be done.

        None when the model returned nothing at all, which `run` lets reach
        `finalize_result` as a failed claim — a turn that got as far as here
        and produced no words has not been answered.
        """
        rendered = render_report([*sources, *failures])
        self.add_details(
            f"writing from {len(sources)} source(s), {len(failures)} failure(s)"
        )
        self.add_details(
            f"rendered: {rendered}"
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
