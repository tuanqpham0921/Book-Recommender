"""What the generation stage is invoked with, and what it produces.

Not a node's `external.py`: nothing downstream consumes a reply, and since the
stage was deregistered (2026-09-08) nothing upstream declares it either. These
types exist for one call — `Orchestrator` builds the input from the task
runner's results map, `GenerationResult` is what the writer fills in, and
`RecommendationsOutput` is what lands in `chat_runs`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.node_input import WorkflowInput
from app.orchestration.task_runner import TaskResult


class RecommendationsInput(WorkflowInput):
    """Everything the plan produced, in the order the runner ran it.

    One undifferentiated list, not the `sources` / `failures` split this used
    to declare. That split was made *for* this stage by `build_input`, matching
    the planner's `depends_on` onto typed fields — and there is no goal and no
    `depends_on` any more, so the partition moved into the executor where the
    whole run is visible. The list is what `TaskRunnerOutput.task_results`
    holds: one `TaskResult` per goal, carrying the node's output (a
    `FailedGoalOutput` for every goal that failed or was skipped), already
    stamped with the instruction that produced it and holding the `preview`
    books the node kept, plus what the goal cost.

    A `WorkflowInput` rather than a `NodeInput` for the same reason
    `TaskRunnerInput` is: this is a pipeline step, not a dispatchable
    capability, so there is no planner instruction to carry. What to write
    about is `results`; what was *asked* is `ctx.user_message`, which this
    stage reads directly because it is the one thing in the app that answers
    the user's turn rather than a goal.

    Defaulted, so a plan where every goal failed still reaches the reply. Only
    an empty list is a caller bug — the orchestrator does not run this stage
    when the runner produced nothing — and the executor raises on it.
    """

    results: list[TaskResult] = Field(default_factory=list)


class TextBlock(BaseModel):
    type: Literal["text"]
    text: str = Field(description="Markdown the user reads. Never a handle.")


class SourceBlock(BaseModel):
    type: Literal["source"]
    refs: list[str] = Field(
        description="Handles like `1.2` of the books the text just before talks about."
    )


class GenerationResult(BaseModel):
    """The reply as the writer fills it in: prose, each part followed by the
    cards it talks about.

    An internal tool like a slice's `*Args` — never seen by the planner, so no
    `node_type`. The wrapper exists because a tool's root must be an object.
    """

    blocks: list[TextBlock | SourceBlock]


class RecommendationsOutput(NodeWorkflowOutput):
    """The turn's reply.

    `blocks` is kept even though it already reached the browser: the stream is
    not readable back, and this is what lands in `chat_runs` and what a later
    conversational turn would read.

    Every field needs a default; the workflow builds its output empty.
    """

    render_evidence: str | None = None
    blocks: list[TextBlock | SourceBlock] = Field(default_factory=list)
    num_books_shown: int = 0

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_books_shown": self.num_books_shown,
            "num_chars": sum(
                len(b.text) for b in self.blocks if isinstance(b, TextBlock)
            ),
        }
