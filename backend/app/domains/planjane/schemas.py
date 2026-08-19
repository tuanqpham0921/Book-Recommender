"""The planner's tool-call schema — what the LLM fills in.

Split from `executor.py` to match the slice layout used elsewhere: `schemas.py`
is what the LLM fills in, `executor.py` is what runs. The goals it produces are
in `external.py`, because they outlive the tool call — the task runner and
triage read them long after the parse is over.
"""

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.common.request_context import RequestContext

from app.common.field_types import MAX_STRING_LENGTH, ReasoningStr
from .external import SystemGoal
from .labels import PlannerNodeTypeEnum
from .prompts.example import planner_example
from airglider import OperationResult

logger = logging.getLogger(__name__)

# The cap the LLM emits under. Lives with the field it bounds, not with the
# goals — `executor.py` reuses it when refusing overflow into `buffer_goals`.
MAX_SYSTEM_GOALS = 10


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
        default_factory=list,
        max_length=5,
        json_schema_extra={"example": "What's the weather like today?"},
    )

    async def __call__(
        self, ctx: "RequestContext", messages: list | None = None
    ) -> OperationResult:
        """Run this already-filled tool schema through the planner's executor.

        The tool schema stays exposed and callable — `AppWorkflow.
        execute_tool_call` dispatches a parsed tool call exactly this way —
        while the goals are
        processed by the one implementation in `PlanJaneExecutor`, which skips
        the parse it no longer needs.

        Returns the executor's envelope. Its `.result` carries the
        `PlanJaneOutput`; on failure the record is the only handle the caller
        has, so check `.ok` rather than assuming an output.

        Imported locally: `executor` imports this module.
        """
        from .executor import PlanJaneExecutor
        from app.domains.node_input import ParsedInput

        planner = PlanJaneExecutor(ctx, messages=messages)
        return await planner(ParsedInput[GoalParseRequest](parsed_result=self))