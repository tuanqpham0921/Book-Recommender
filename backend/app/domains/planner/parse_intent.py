import json
import logging
from typing import Any, Optional, Literal, cast
from openai.types.chat import ParsedFunctionToolCall
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
    ValidationError,
)

from app.common.messages import AssistantMessage, APIMessage, ToolMessage, UserMessage
from app.common.prompt_loader import format_prompt, load_prompt
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.node_types import NodeTypeEnum
from app.registry import NODE_TYPE_TO_CLS, format_node_type_catalog
from clients import OpenAIParserRequest
from clients.base import BaseLLMClient
from clients.openai_requests import OpenAIChatRequest
from common.utils import uuid_8
from .node_types import PlannerNodeTypeEnum
from app.domains.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    DescriptionStr,
    ReasoningStr,
    OptionalStr,
)
from .prompts.example import planner_example

logger = logging.getLogger(__name__)

GOAL_GENERATOR_PROMPT_PATH = "domains/planner/prompts/0_goal_generator.txt"
# PLAYGORUND_PROMPT_PATH = "../playground/prompting/planner_prompt._extended.txt"

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
    
    id: str = Field(...,
                description="assign an id for this goal",
                json_schema_extra={"example": ["1", "2"]}
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
        json_schema_extra={"example": ["1", "2"]}
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

    model_config = ConfigDict(
        json_schema_extra=planner_example
    )

    node_type: Literal[PlannerNodeTypeEnum.PARSE_INTENT] = (
        PlannerNodeTypeEnum.PARSE_INTENT
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
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "What's the weather like today?"},
    )


class InitialParseOutput(AppWorkflowOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    out_of_scope: list[str] = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "total_system_goals": len(self.accepted_goals) + len(self.refused_goals),
            "num_rejected_system": len(self.refused_goals),
            "num_accepted_system": len(self.accepted_goals),
            "out_of_scope": self.out_of_scope,
        }

    def accepted_goals_ids(self) -> list[str]:
        return [goal.id for goal in self.accepted_goals]

    def to_llm_messages(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.out_of_scope:
            payload["out_of_scope"] = self.out_of_scope
        if self.refused_goals:
            payload["refused_goals"] = [
                (g.description, g.refusal_reasons) for g in self.refused_goals
            ]

        return payload


class InitialParseWorkflow(AppBaseWorkflow[InitialParseOutput]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    ui_loading_message = "Thinking..."
    intent_reject_message = (
        "I can't help with that request. Please try again with a book-related question."
    )
    continuation_reject_message = "I don't have memory of earlier messages yet — please restate your full request in one message."

    tool_models: list[type] = [GoalParseRequest]

    def __init__(
        self,
        sse_stream: SSEStream,
        user_message: UserMessage,
        llm_client: BaseLLMClient,
        messages=None,
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=InitialParseOutput,
            messages=messages,
        )
        self.user_message = user_message

    async def run(self) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        tool_call = await self._run_llm_args_parse()
        # parsed_arguments is typed `object | None` by the openai lib; the
        # parser validated it against GoalParseRequest, so the cast holds
        parse_result = cast(GoalParseRequest, tool_call.function.parsed_arguments)
        self.process_parse_result(parse_result)
        self._record_tool_call(tool_call)
        payload = self.output.to_llm_messages()
        await self.finalize_result(payload)
        
        # generate unable to help with
        if self.result.output.out_of_scope:
            await self.sse_stream.send_chars("\n\n I can't do:\n")
            for unsupported in self.result.output.out_of_scope:
                await self.sse_stream.send_chars(f"- {unsupported}\n")
        

    async def _run_llm_args_parse(self) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=GOAL_GENERATOR_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=format_node_type_catalog(),
        )
        
        # NOTE: toggle on for prompting experiments
        # system_prompt = load_prompt(prompt_path=PLAYGORUND_PROMPT_PATH)
        
        # NOTE: using gpt4.1 because the system goals sees the whole catalog
        # it's very important that this part is done correctly
        # cache hit rate is high, and output generation is lower
        # we can optimize
        req = OpenAIParserRequest(
            prompt=system_prompt,
            model="gpt-5.6-terra",
            reasoning_effort = "none",
            # NOTE: this should be a list of previous messages as well
            # but for now we can just do clear and direct instructions
            messages=[self.user_message],
            tool_models=[GoalParseRequest],
        )
        assistant_msg = await self.run_llm_call(req)
        tool_calls = assistant_msg.tool_calls
        if not tool_calls:
            # previously an unguarded [0] on None — same failure semantics
            # (runtime error caught by the workflow), clearer message
            raise ValueError("LLM response contained no tool calls")
        return tool_calls[0]

    def _record_tool_call(self, tool_call: ParsedFunctionToolCall) -> None:
        self.messages.append(
            ToolMessage(
                name=tool_call.function.name,
                tool_call_id=tool_call.id,
                content=self.output,
            )
        )

    async def finalize_result(self, payload) -> None:
        # ok = the conversation was handled: either there are goals to plan,
        # or a substantive reply (out-of-scope / refusals) was
        # streamed to the user. The orchestrator decides continuation from
        # accepted_goals, not from ok.
        super().finalize_result(ok=bool(self.output.accepted_goals or payload))

    def process_parse_result(
        self, parse_result: GoalParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if (
            len(parse_result.system_goals) == 0
            and not parse_result.out_of_scope
        ):
            logger.warning("Nothing was classified in the initial parse")
            self.result.ok = False
            self.result.add_details("Nothing was classified in the initial parse")
            raise RuntimeError("Nothing was classified in the initial parse")

        self.output.out_of_scope = parse_result.out_of_scope

        # overflow goals are valid, just over the model's limit — run them
        # through the same checks so they can fill capacity freed by refusals,
        # or wait in buffer_goals
        all_goals = parse_result.system_goals
        for goal in all_goals:
            reasons = []
            if goal.confidence < confident_tuning:
                reasons.append(f"Rejected: confidence too low ({goal.confidence})")
            if goal.target_node_type.value not in NODE_TYPE_TO_CLS.keys():
                reasons.append(
                    f"Rejected: target node type not supported ({goal.target_node_type})"
                )
            if reasons or goal._refusal:
                goal.refuse(*reasons)
                self.output.refused_goals.append(goal)
            elif len(self.output.accepted_goals) < MAX_SYSTEM_GOALS:
                self.output.accepted_goals.append(goal)
            else:
                self.output.buffer_goals.append(goal)
