"""The planner's tool-call schemas — what the LLM fills in, and the goal model.

Split from `executor.py` to match the slice layout the rest of the repo uses
(`schemas.py` = what the LLM fills in, `executor.py` = what runs). The split
originally also broke an import cycle through the generation-node module; that
module is gone, so the layout convention is the whole reason now.
"""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.registry import NodeTypeEnum
from app.domains.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    DescriptionStr,
    ReasoningStr,
)
from .labels import PlannerNodeTypeEnum
from .prompts.example import planner_example

logger = logging.getLogger(__name__)

MAX_SYSTEM_GOALS = 10


class SystemGoal(BaseModel):
    """Purpose: One parsed goal from the user's message — a capability the
    system should attempt, with the confidence that it maps cleanly to a
    supported node type. One entry in GoalParseRequest.system_goals.

    Args:
        id: A short id for this goal, in the form '1', '2', ... — other
            goals reference it through their depends_on.
        description: A short and instructive decription of this node.
        confidence: How confident the system is that it can fulfill this goal.
        reasoning: A short justification for choosing this goal (up to 100
            characters).
        target_node_type: The single capability name from the catalog that
            fulfills this goal.
        depends_on: Ids of the goals that must complete before this one;
            an empty list when it depends on nothing.

    Returns: One candidate goal that the argument parser later fills in with
    typed arguments, or refuses.

    Constraints: exactly one target_node_type per goal — a multi-part
    request becomes separate goals, not one goal with multiple types.
    """

    node_type: Literal[PlannerNodeTypeEnum.SYSTEM_GOAL] = (
        PlannerNodeTypeEnum.SYSTEM_GOAL
    )

    id: str = Field(
        ...,
        description="assign an id for this goal",
        json_schema_extra={"example": ["1", "2"]},
    )

    description: DescriptionStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "Find Dune by title"},
    )
    reasoning: ReasoningStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "Direct match to a supported capability"},
    )
    confidence: ConfidenceFloat = Field(
        ...,
        ge=MIN_CONFIDENCE,
        le=MAX_CONFIDENCE,
        json_schema_extra={"example": 1.0},
    )

    target_node_type: NodeTypeEnum = Field(
        ...,
        json_schema_extra={"example": "Retrieve_by_Title"},
    )
    depends_on: list[str] = Field(
        ...,
        description="List of goals_id must be completed before this",
        json_schema_extra={"example": ["1", "2"]},
    )

    _refusal: bool = PrivateAttr(default=False)
    _refusal_reasons: list[str] = PrivateAttr(default_factory=list)
    # _id: str = PrivateAttr(default_factory=lambda: f"goal_{uuid_8()}")

    # @property
    # def id(self) -> str:
    #     return self._id

    @property
    def refusal_reasons(self) -> list[str]:
        return self._refusal_reasons

    def refuse(self, *reasons: str) -> None:
        self._refusal = True
        self._refusal_reasons.extend(reasons)

    def get_depends_on(self):
        return self.depends_on


class GoalParseRequest(BaseModel):
    """Purpose: Goals parse of the user's message — the tool call for the
    parse-intent LLM step. Splits the message into system_goals (mapped
    capabilities), and out_of_scope content.

    Args:
        out_of_scope: The out-of-domain portion of the message, when present.
        system_goals: One SystemGoal per capability the message maps to;
            empty when nothing in-domain was found.

    Returns: The parsed breakdown — system_goals feed the argument parser
    and execution; out_of_scope feeds the response step.

    Constraints: at most MAX_SYSTEM_GOALS (10) goals per call; every
    in-domain part of the message should map to exactly one goal.
    """

    model_config = ConfigDict(json_schema_extra=planner_example)

    node_type: Literal[PlannerNodeTypeEnum.PLAN_JANE] = (
        PlannerNodeTypeEnum.PLAN_JANE
    )

    system_goals: list[SystemGoal] = Field(
        default_factory=list,
        max_length=MAX_SYSTEM_GOALS,
    )

    reasoning: ReasoningStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "Direct match to a supported capability"},
    )

    out_of_scope: list[str] = Field(
        default=None,
        max_length=5,
        json_schema_extra={"example": "What's the weather like today?"},
    )
