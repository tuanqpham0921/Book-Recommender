import json
import logging
from typing import Any, Optional, Literal, cast
from openai.types.chat import ParsedFunctionToolCall
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator, ValidationError

from app.common.messages import AssistantMessage, APIMessage, ToolMessage, UserMessage
from app.common.prompt_loader import format_prompt
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
    OptionalStr
)

logger = logging.getLogger(__name__)

INITIAL_SYSTEM_PROMPT_PATH = "domains/planner/prompts/0_initial_system.txt"
INITIAL_PARSE_RESPONSE_PROMPT_PATH = (
    "domains/planner/prompts/1_initial_parse_response.txt"
)

MAX_SYSTEM_GOALS = 10


class SystemGoal(BaseModel):
    node_type: Literal[PlannerNodeTypeEnum.SYSTEM_GOAL] = PlannerNodeTypeEnum.SYSTEM_GOAL

    description: DescriptionStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        description="Description of the system goal",
    )
    confidence: ConfidenceFloat = Field(
        ...,
        ge=MIN_CONFIDENCE,
        le=MAX_CONFIDENCE,
        description="Confidence between 0 and 1 that the system can handle this goal",
    )

    target_node_type: NodeTypeEnum = Field(
        ...,
        description="the node type to complete this goal",
    )

    _refusal: bool = PrivateAttr(default=False)
    _refusal_reasons: list[str] = PrivateAttr(default_factory=list)
    _id: str = PrivateAttr(default_factory=lambda: f"goal_{uuid_8()}")

    @property
    def id(self) -> str:
        return self._id

    @property
    def refusal_reasons(self) -> list[str]:
        return self._refusal_reasons

    def refuse(self, *reasons: str) -> None:
        self._refusal = True
        self._refusal_reasons.extend(reasons)

class InitialParseRequest(BaseModel):
    """
    Initial parse for the Book Recommender: extract system_goals with confidence,
    and separate small_talk and out_of_scope from in-domain requests.
    """
    node_type: Literal[PlannerNodeTypeEnum.PARSE_INTENT] = PlannerNodeTypeEnum.PARSE_INTENT

    small_talk: OptionalStr = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        description="Small talk in the request",
    )
    out_of_scope: OptionalStr = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        description="Out-of-domain content",
    )
    system_goals: list[SystemGoal] = Field(
        default_factory=list,
        max_length=MAX_SYSTEM_GOALS,
        description="System goals for the query",
    )
    reasoning: ReasoningStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        description="Reasoning for classification",
    )
    
    _overflow_system_goals: list[SystemGoal] = PrivateAttr(default_factory=list)
    _invalid_system_goals: list = PrivateAttr(default_factory=list)

    @model_validator(mode="wrap")
    @classmethod
    def capture_system_goals(cls, data, handler):
        raw = data.get("system_goals", []) if isinstance(data, dict) else []
        if not isinstance(raw, list):
            raw = [raw]

        valid, invalid = [], []
        for item in raw:
            if isinstance(item, SystemGoal):
                valid.append(item)
                continue

            try:
                goal_instance = SystemGoal.model_validate(item)
                valid.append(goal_instance)
            except ValidationError as e:
                logger.exception(e)
                invalid.append(item)

        if isinstance(data, dict):
            data["system_goals"] = valid[:MAX_SYSTEM_GOALS]

        instance = handler(data)  # Pydantic builds the instance
        instance._overflow_system_goals = valid[MAX_SYSTEM_GOALS:]
        instance._invalid_system_goals = invalid
        return instance


class InitialParseOutput(AppWorkflowOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    small_talk: Optional[str] = None
    out_of_scope: Optional[str] = None
    reasoning: Optional[str] = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "total_system_goals": len(self.accepted_goals) + len(self.refused_goals),
            "num_rejected_system": len(self.refused_goals),
            "num_accepted_system": len(self.accepted_goals),
            "small_talk": self.small_talk,
            "out_of_scope": self.out_of_scope,
            "reasoning": self.reasoning,
        }

    def accepted_goals_ids(self) -> list[str]:
        return [goal.id for goal in self.accepted_goals]

    def to_llm_messages(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.small_talk:
            payload["small_talk"] = self.small_talk
        if self.out_of_scope:
            payload["out_of_scope"] = self.out_of_scope
        if self.refused_goals:
            payload["refused_goals"] = [
                (g.description, g.refusal_reasons) for g in self.refused_goals
            ]
        if len(payload) > 0 and self.reasoning:
            payload["reasoning"] = self.reasoning

        return payload


class InitialParseWorkflow(AppBaseWorkflow[InitialParseOutput]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    ui_loading_message = "Thinking..."

    tool_models: list[type] = [InitialParseRequest]

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
        # parser validated it against InitialParseRequest, so the cast holds
        parse_result = cast(InitialParseRequest, tool_call.function.parsed_arguments)
        self.process_parse_result(parse_result)
        self._record_tool_call(tool_call)
        payload = self.output.to_llm_messages()
        await self.finalize_result(payload)
        await self.generate_user_response(payload)
        
    async def _run_llm_args_parse(self) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=INITIAL_SYSTEM_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=format_node_type_catalog(),
        )
        req = OpenAIParserRequest(
            prompt=system_prompt,
            # NOTE: this should be a list of previous messages as well
            # but for now we can just do clear and direct instructions 
            messages=[self.user_message], 
            tool_models=self.tool_models,
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
        # or a substantive reply (small talk / out-of-scope / refusals) was
        # streamed to the user. The orchestrator decides continuation from
        # accepted_goals, not from ok.
        super().finalize_result(ok=bool(self.output.accepted_goals or payload))

    async def generate_user_response(self, payload) -> None:
        if not payload:
            return

        messages: list[APIMessage] = [AssistantMessage(content=json.dumps(payload))]
        response_prompt = format_prompt(
            prompt_path=INITIAL_PARSE_RESPONSE_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=format_node_type_catalog(),
        )
        await self.run_llm_call(
            req=OpenAIChatRequest(
                prompt=response_prompt,
                messages=messages,
                sse_stream=self.sse_stream,
                temperature=0.7,
                top_p=1.0,
            ),
        )
        await self.sse_stream.send_divider()

    def process_parse_result(
        self, parse_result: InitialParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if (
            len(parse_result.system_goals) == 0
            and not parse_result.small_talk
            and not parse_result.out_of_scope
        ):
            logger.warning("Nothing was classified in the initial parse")
            self.result.ok = False
            self.output.reasoning = "Nothing was classified in the initial parse"
            return

        self.output.small_talk = parse_result.small_talk
        self.output.out_of_scope = parse_result.out_of_scope
        self.output.reasoning = parse_result.reasoning

        # overflow goals are valid, just over the model's limit — run them
        # through the same checks so they can fill capacity freed by refusals,
        # or wait in buffer_goals
        all_goals = parse_result.system_goals + parse_result._overflow_system_goals
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
