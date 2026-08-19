"""What PlanJane exposes to the layers around it: the plan, the goal it is made
of, and the order those goals run in.

`schemas.py` is what the *LLM* fills in; this is what the rest of the app reads
back. `SystemGoal` sits here rather than there because it is both — the planner
LLM emits it as a nested tool schema, and then it travels: the task runner
dispatches one per node, triage layers them, `run_recorder` serializes them. A
consumer importing it should not have to reach through the tool schema that
produced it, and `executor.py` should not be the address for a payload.

Imports `schemas.py` for nothing — the dependency runs the other way
(`GoalParseRequest.system_goals` is a `list[SystemGoal]`), which is what keeps
this module importable without pulling in the planner's prompt example.
"""

import logging
from collections import defaultdict
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field, PrivateAttr

from app.domains.base_workflow import NodeWorkflowOutput
from app.common.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    DescriptionStr,
    ReasoningStr,
)
from app.registry import NodeTypeEnum

from .labels import PlannerNodeTypeEnum

logger = logging.getLogger(__name__)


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

    @property
    def refusal_reasons(self) -> list[str]:
        return self._refusal_reasons

    def refuse(self, *reasons: str) -> None:
        self._refusal = True
        self._refusal_reasons.extend(reasons)


class ExecutionOrder(NamedTuple):
    """The accepted goals arranged for execution.

    `layers` is a dependency layering: a goal depends only on earlier layers, so
    a layer is safe to run in any order or concurrently — which is the only
    reason to group. Running them flattened is therefore also correct.

    `unreachable` is every goal no layer could contain: in a cycle, or depending
    on one the planner refused. Returned rather than dropped — omitting them is
    how a user asks for three things, gets one, and is told it succeeded.
    """

    layers: list[list[SystemGoal]]
    unreachable: list[SystemGoal]


class PlanJaneOutput(NodeWorkflowOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    # Optional, not `list[str] = None`: model_dump_json emits `null` when
    # unset, and a non-optional annotation then rejects its own dump on reload.
    out_of_scope: list[str] | None = None

    # The rendered plan — plan presentation belongs to the plan.
    diagram: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "accepted_types": [goal.target_node_type for goal in self.accepted_goals],
            "num_rejected_system": len(self.refused_goals),
            "out_of_scope": self.out_of_scope,
        }

    def accepted_goals_ids(self) -> list[str]:
        return [goal.id for goal in self.accepted_goals]

    def id_to_node(self) -> dict[str, SystemGoal]:
        """The accepted goals keyed by the id other goals reference them by."""
        return {goal.id: goal for goal in self.accepted_goals}

    def execution_order(self) -> ExecutionOrder:
        """Layer the accepted goals by dependency depth (Kahn's algorithm).

        Each round emits every goal whose dependencies are all placed, then
        decrements the goals waiting on them. `ready` and `next_ready` are
        separate lists so the layer boundary holds by construction — snapshotting
        one queue's length while still pushing onto it is what let a goal share a
        layer with the dependency that unblocked it.

        A goal that never reaches zero is returned in `unreachable` rather than
        vanishing: a cycle, or a dependency the planner refused.
        """
        goals = self.id_to_node()

        # goal id -> the goals waiting on it, and how many each still waits
        # for. Both sides come off the same de-duplicated list, so a goal naming
        # a dependency twice is counted and decremented the same number of times.
        dependents: dict[str, list[str]] = defaultdict(list)
        blocked_by: dict[str, int] = {}
        for goal_id, goal in goals.items():
            deps = list(dict.fromkeys(goal.depends_on))
            # An unknown dependency id is counted but wired to nothing, so it
            # can never be decremented — which is what makes this goal come back
            # unreachable rather than run without its input.
            for dep_id in deps:
                if dep_id in goals:
                    dependents[dep_id].append(goal_id)
            blocked_by[goal_id] = len(deps)

        layers: list[list[SystemGoal]] = []
        ready = [goal_id for goal_id in goals if blocked_by[goal_id] == 0]
        while ready:
            layers.append([goals[goal_id] for goal_id in ready])

            next_ready: list[str] = []
            for goal_id in ready:
                for dependent_id in dependents[goal_id]:
                    blocked_by[dependent_id] -= 1
                    if blocked_by[dependent_id] == 0:
                        next_ready.append(dependent_id)
            ready = next_ready

        # by construction: anything no layer claimed could not be scheduled
        scheduled = {goal.id for layer in layers for goal in layer}
        unreachable = [
            goal for goal in goals.values() if goal.id not in scheduled
        ]
        if unreachable:
            logger.warning(
                "Goals that can never run (cycle, or depend on a refused "
                f"goal): {[goal.id for goal in unreachable]}"
            )

        return ExecutionOrder(layers=layers, unreachable=unreachable)
