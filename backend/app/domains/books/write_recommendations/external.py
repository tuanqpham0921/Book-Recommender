"""What the generation node is invoked with, and what it produces.

Unlike a retrieval slice's `external.py` there is no downstream consumer to
serve — nothing composes on a reply. These types exist for the dispatch seam:
`RecommendationsInput` is what `build_input` assembles from the plan, and
`RecommendationsOutput` is what lands in `chat_runs` beside the prose that
already streamed to the browser.
"""

from typing import Any

from pydantic import Field

from app.domains.base_workflow import FailedGoalOutput, NodeWorkflowOutput
from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput


class RecommendationsInput(NodeInput):
    """What the reply is written from: every book-producing dependency, and
    every dependency that never produced one.

    `sources` takes the *base* shape on purpose (the `CombineIntersectInput`
    precedent): how a set was found stops mattering once it is being presented,
    so anchors, candidate sets and intersections all land here. `failures` is
    the other half of the same story — the runner records a `FailedGoalOutput`
    for a goal that failed or was skipped, and this is the one input that
    declares a slot for them, which is how "I couldn't find Dune, so…" gets
    written by the only stage that speaks to the user.

    Both default: a branch whose every step failed still gets its reply (all
    `failures`, no `sources`). Only *both* empty is a malformed plan — a
    generation goal depending on nothing — and the executor raises on it
    rather than the requirement living here, so the section reports the
    failure instead of silently vanishing from the turn.
    """

    sources: list[BookRetrievalOutput] = Field(default_factory=list)
    failures: list[FailedGoalOutput] = Field(default_factory=list)


class RecommendationsOutput(NodeWorkflowOutput):
    """The reply for one recommendation chain.

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
