"""The terminal answer stage: a generation node attached to every sink in the plan.

Generation is deliberately **not** a planner goal. The LLM never selects it, so
it costs no catalog tokens, can never be misrouted, and can never be missing
from a plan — the planner appends it after parsing instead. That is why this
lives under `planner/` rather than in `app/domains/books/` or `app/registry.py`.
See docs/design/execution-pipeline-v1.md ("Generation node").

A node is at the end of the DAG when **nothing depends on it** (a sink). That is
not a depth property: a plan can have several sinks at different depths (one per
independent goal in a compound message), and the node with the most dependencies
is very often not terminal — a Compare fed by four retrievals is a sink only if
no Recommend consumes it.
"""

from enum import Enum

from pydantic import BaseModel, Field

from .schemas import SystemGoal

GENERATION_ID_PREFIX = "gen_"


class GenerationTypeEnum(str, Enum):
    RECOMMENDATION_ANSWER = "recommend_answer"
    ACTION_CONFIRMATION_ANSWER = "confirmed_action"
    COMPARISON_ANSWER = "comparison_answer"
    PROJECT_INFO_ANSWER = "project_info_answer"
    USER_META_DATA_ANSWER = "user_meta_data_answer"
    BOOK_INFO_ANSWER = "book_info_answer"
    AUTHOR_INFO_ANSWER = "author_info_answer"
    UNKNOWN_FAILURE_ANSWER = "unknown_failure_answer"

    GENERIC_RESPONSE = "generic_answer"


class GenerationNode(BaseModel):
    """One user-facing answer, written from the output of the goals it depends on.

    Carries `id` and `depends_on` as real fields (not the `_id`/`_depends_on`
    private attrs `BaseRequest` uses) because nothing here is LLM-filled — the
    planner constructs it directly, and the Mermaid renderer keys nodes by `id`
    and draws edges from `depends_on`.
    """

    node_type: GenerationTypeEnum = GenerationTypeEnum.GENERIC_RESPONSE
    id: str = Field(..., description="Plan id for this answer step")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Ids of the goals whose output this answer is written from",
    )

    def get_depends_on(self) -> list[str]:
        """Mirrors BaseRequest.get_depends_on so plan-walking code can treat
        generation nodes like any other node."""
        return self.depends_on


def find_sink_goals(goals: list[SystemGoal]) -> list[SystemGoal]:
    """The goals nothing else depends on — the ends of the DAG.

    Order follows `goals`, so the generation nodes come out in plan order.
    """
    depended_on = {dep for goal in goals for dep in goal.depends_on}
    return [goal for goal in goals if goal.id not in depended_on]


def create_generation_nodes(
    goals: list[SystemGoal], *, single_answer: bool = False
) -> list[GenerationNode]:
    """Attach the answer stage to the end of the plan.

    Default is one generation node per sink, so each independent branch of a
    compound message ("tell me about the project AND recommend a sci-fi book")
    gets its own answer. `single_answer=True` collapses to one node depending on
    every sink — use it when one writer should own ordering and framing across
    the whole turn.
    """
    if not goals:
        return []

    # No sinks means every goal is depended on by another, i.e. a cycle. The
    # plan is invalid, but answering nothing is worse than answering from
    # everything, so fall back to the full goal list rather than returning [].
    sinks = find_sink_goals(goals) or list(goals)

    if single_answer:
        return [
            GenerationNode(
                id=f"{GENERATION_ID_PREFIX}1",
                depends_on=[goal.id for goal in sinks],
            )
        ]

    return [
        GenerationNode(id=f"{GENERATION_ID_PREFIX}{index}", depends_on=[goal.id])
        for index, goal in enumerate(sinks, start=1)
    ]
