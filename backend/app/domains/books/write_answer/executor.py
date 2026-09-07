"""The answer stage's flow. `run` is the table of contents; everything else sits
where the flow reaches it.

Same reading rule as the other slices (domains/README.md): this file is the flow
— `run()` plus every step, in the order `run` reaches them — and `render.py` is
the one LLM call's pure half.

**This slice has no `SPEC`, no `labels.py` and no entry in `guide.py`, and that
absence is the design.** The planner never sees this stage, so it cannot be
misrouted onto it, cannot omit it, and no eval golden carries it. What decides
that an answer happens is structural: `TaskRunnerWorkflow` attaches one to every
sink in the plan. See docs/design/execution-pipeline-v1.md.

It is the terminal stage, so it is also the only thing left that can materialize
rows: counts-first means every node hands on a `DeferredBookQuery` and nothing
else fetches. That is why it subclasses `BookReaderWorkflow` — it reads and
shows books while producing prose rather than a count.
"""

from app.domains.books.base_workflow import BookReaderWorkflow
from app.domains.books.schemas import Book
from airglider import task

from .external import AnswerInput, AnswerOutput, AnswerStep
from .render import build_answer_request, render_branch

# Rows fetched per step. Larger than `BookConstraints.default_limit` (3), which
# sizes a preview in a section nobody expands — these are the cards the answer
# is actually about, and the writer needs enough of them to say something true
# about the set rather than about three arbitrary members of it.
ANSWER_ROW_LIMIT = 5

# How many steps in one branch get a round trip. A branch is a sink plus its
# ancestors, so this is small in practice; the cap is what stops a wide plan
# turning one answer into a dozen materializations. The sink is fetched first,
# so what a cap drops is always the least specific end of the branch.
MAX_MATERIALIZED_STEPS = 4

# Cards land one at a time here, unlike a preview's instant dump: this is the
# answer, and the arrival is part of reading it.
CARD_DELAY = 0.03


class AnswerWorkflow(BookReaderWorkflow[AnswerOutput]):
    ui_loading_message = "Writing your answer..."
    ui_section_title = "Answer"
    # the reply is the point of the turn — never folded away
    ui_section_collapsible = False

    async def run(self, node_input: AnswerInput) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        steps = node_input.steps

        # 1. materialize. The one place in the app rows are fetched to be kept:
        # every node upstream counted and handed on its query.
        rows = (await self.materialize(steps)).unwrap()

        # 2. cards, before the prose. One `stream_books` call rather than one
        # per step, because its isbn13 dedup is per call — a branch that found
        # Dune and then books like Dune must not show Dune twice.
        shown = [book for books in rows for book in books]
        await self.stream_books(shown, delay=CARD_DELAY)
        self.result.num_books_shown = len(shown)

        # 3. the reply. It reaches the browser from inside this call — the
        # request carries the SSE stream and the client pushes each delta — so
        # what comes back is for the record, not for sending.
        self.result.text = (await self.write_answer(steps, rows)).unwrap()

        # 4. last: ok is read off the output
        self.finalize_result()

    @task
    async def materialize(self, steps: list[AnswerStep]) -> list[list[Book]]:
        """Rows for each step, positional against `steps`.

        Empty lists for the steps that have nothing to fetch — one that failed,
        one that matched nothing, one past the cap — so the renderer can zip the
        two lists and still tell those cases apart from its own `num_books`.

        Fetched sink-first (`steps` is ordered sink-last, so this walks it in
        reverse) and re-sorted afterwards: when the cap bites, what survives is
        the goal the branch was working toward rather than whichever ancestor
        happened to come first.
        """
        rows: dict[int, list[Book]] = {}
        budget = MAX_MATERIALIZED_STEPS

        for index in reversed(range(len(steps))):
            step = steps[index]
            if step.failed or not step.num_books or step.output is None:
                continue
            if step.output.query is None:
                # every registered node fills `query`; a mock or a future node
                # that does not is a step the answer can still count, not fetch
                self.add_details(f"step {index + 1} has a count but no query")
                continue
            if not budget:
                self.add_details(f"step {index + 1} not materialized (cap reached)")
                continue

            budget -= 1
            fetched = await self.fetch_books(step.output.query, ANSWER_ROW_LIMIT)
            rows[index] = fetched.unwrap()

        return [rows.get(index, []) for index in range(len(steps))]

    @task
    async def write_answer(
        self, steps: list[AnswerStep], rows: list[list[Book]]
    ) -> str | None:
        """The reply, streamed to the browser as it is written.

        A `@task` so the call's spend and duration are attributed to the writing
        rather than to the fetches before it. Not a `Workflow`: the payload is a
        string, with no declared output type to carry.

        None when the model returned nothing at all, which `run` lets reach
        `finalize_result` as a failed claim — a branch that got as far as here
        and produced no words has not been answered.
        """
        rendered = render_branch(steps, rows)
        self.add_details(f"answering from {len(steps)} step(s)")

        req = build_answer_request(
            rendered, self.sse_stream, self.user_message.content
        )
        message = await self.run_llm_call(req)
        return message.content

    def finalize_result(self) -> None:
        """ok means the branch was reported on, not that books were found.

        A branch whose every step came back empty is a correct answer — "I don't
        have that, so I couldn't look for anything like it" is the reply, and
        marking it failed would surface the generic error message instead and
        tell the user nothing.
        """
        super().finalize_result(ok=bool(self.result.text))
