"""What the answer stage is invoked with, and what it produces.

Unlike every other slice's `external.py` there is no downstream consumer to
serve: nothing depends on an answer, because an answer is where a branch ends.
These types exist for the one caller that builds them —
`TaskRunnerWorkflow._write_answers` — which is also why `AnswerInput` is a
`WorkflowInput` and not a `NodeInput`: it is constructed directly rather than
assembled by `build_input`, so there is no type-matching to satisfy and no
`query` field to fill.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import WorkflowInput


class AnswerStep(BaseModel):
    """One goal in the branch: what it was asked to do, and what came of it.

    `description` is a plain string rather than the `SystemGoal` it came off,
    and that is deliberate: it keeps the books domain from importing the
    planner for a field the writer only reads as prose.

    The three states a step can be in are all real and all say something
    different to the writer. A step with an output and `num_books > 0` found
    books. A step with an output and `num_books == 0` ran correctly and found
    none — an answer, not a failure. A step with `failed=True` never produced
    one, and the branch has to say what could not be done because of it.
    """

    description: str
    output: BookRetrievalOutput | None = None
    failed: bool = False

    @property
    def num_books(self) -> int:
        return self.output.num_books if self.output else 0


class AnswerInput(WorkflowInput):
    """One branch of the plan: a sink and its ancestors, sink last.

    `min_length=1` because a branch is built from a sink, so there is always at
    least the sink itself — an empty one means the caller assembled it wrong,
    and failing here says so rather than producing an answer about nothing.
    """

    steps: list[AnswerStep] = Field(..., min_length=1)


class AnswerOutput(NodeWorkflowOutput):
    """The reply for one branch.

    `text` is kept even though the prose already reached the browser as it was
    generated: the stream is not readable back, and this is what lands in
    `chat_runs` and what a later conversational turn would read. Both come from
    the same call — `OpenAIChatRequest` streams deltas to the SSE stream and
    still returns the assembled message.

    Every field needs a default; the workflow builds its output empty.
    """

    text: str | None = None
    num_books_shown: int = 0

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_books_shown": self.num_books_shown,
            "num_chars": len(self.text) if self.text else 0,
        }
