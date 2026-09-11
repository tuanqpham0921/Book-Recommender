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
from app.domains.books.schemas import Book
from app.orchestration.task_runner import TaskResult
from airglider import task

from .external import (
    GenerationResult,
    RecommendationsInput,
    RecommendationsOutput,
    SourceBlock,
    TextBlock,
)
from .render import books_by_handle, build_recommendations_request, render_report

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
        self.add_details(
            f"writing from {len(sources)} source(s), {len(failures)} failure(s)"
        )

        # Sources first, so the report reads what was found before what could
        # not be done. One list for the report and the handles both, so a
        # handle the model copies resolves to the book it read.
        ordered = [*sources, *failures]

        # 1. the reply, as blocks — nothing reaches the browser until it is
        # whole, because each text decides which cards follow it
        reply = (await self.write_recommendations(ordered)).unwrap()
        self.result.blocks = reply.blocks

        # 2. each text, then the cards it talks about
        await self._deliver(reply.blocks, books_by_handle(ordered))

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
        self, results: list[TaskResult]
    ) -> GenerationResult:
        """The reply, as text blocks and the cards each one talks about.

        A `@task` so the call's spend and duration are attributed to the
        writing rather than to the sending after it. Not a `Workflow`: the
        payload is the tool's parsed arguments, with no output of its own to
        carry.
        """
        rendered = render_report(results)
        self.result.render_evidence = rendered

        req = build_recommendations_request(rendered, self.user_message.content)

        # TODO: add the assistant message into here
        from clients.messages import AssistantMessage
        self.messages.append(AssistantMessage(content=rendered))

        return await self.run_llm_args_parse(req)

    async def _deliver(
        self, blocks: list[TextBlock | SourceBlock], books: dict[str, Book]
    ) -> None:
        """Send the reply in the order it was written: a text as characters, a
        source as the cards it names.

        The frontend needs nothing for this — a card after text opens a card
        row, text after a card opens a paragraph. Two texts in a row land in
        one text section, so each ends on a blank line to stay a paragraph.

        `shown` spans the whole reply rather than one `stream_books` call,
        whose isbn13 dedup is per call: Dune found by title and again as its
        own neighbour is two handles and one card. A ref the report never
        printed is the model naming a book it was not given, so it is dropped.
        """
        shown: set[str | None] = set()
        for block in blocks:
            if isinstance(block, TextBlock):
                await self.sse_stream.send_chars(block.text + "\n\n")
                continue

            cards: list[Book] = []
            for ref in block.refs:
                book = books.get(ref)
                if book is None:
                    self.add_details(f"dropped ref {ref!r}: not in the report")
                elif book.isbn13 not in shown:
                    shown.add(book.isbn13)
                    cards.append(book)
            await self.stream_books(cards, delay=CARD_DELAY)

        self.result.num_books_shown = len(shown)

    def finalize_result(self) -> None:
        """ok means the turn was reported on, not that books were found.

        A reply over empty sources — or over nothing but failures — is a
        correct answer: "I don't have that, so I couldn't look for anything
        like it" is the reply, and marking it failed would surface the generic
        error message instead and tell the user nothing. A reply with no words
        — no blocks, or only cards — has not answered anything.
        """
        super().finalize_result(
            ok=any(
                isinstance(block, TextBlock) and block.text.strip()
                for block in self.result.blocks
            )
        )
