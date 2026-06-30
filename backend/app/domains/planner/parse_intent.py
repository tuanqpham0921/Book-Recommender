import json
import logging
from typing import Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator

from app.common.messages import AssistantMessage, UserMessage
from app.common.prompt_loader import format_prompt, load_prompt
from app.common.sse_stream import SSEStream
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.domains.base_request import (
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    MIN_CONFIDENCE,
    MIN_STRING_LENGTH,
)
from app.domains.node_types import NodeTypeEnum
from app.domains.registry import NODE_TYPE_TO_CLS, format_node_type_catalog
from clients import OpenAIParserRequest
from clients.openai_client import OpenAIClient
from clients.openai_requests import OpenAIChatRequest
from common.utils import uuid_8

logger = logging.getLogger(__name__)

INITIAL_SYSTEM_PROMPT_PATH = "domains/planner/prompts/0_initial_system.txt"
INITIAL_PARSE_RESPONSE_PROMPT_PATH = "domains/planner/prompts/1_initial_parse_response.txt"

MAX_SYSTEM_GOALS = 10


class SystemGoal(BaseModel):
    description: str = Field(
        ...,
        min_length=MIN_STRING_LENGTH,
        max_length=MAX_STRING_LENGTH,
        description="Description of the system goal",
    )
    confidence: float = Field(
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

    @field_validator("confidence", mode="before")
    @classmethod
    def check_confidence(cls, value):
        if not isinstance(value, (float, int)):
            return MIN_CONFIDENCE
        if not (MIN_CONFIDENCE <= value <= MAX_CONFIDENCE):
            return MIN_CONFIDENCE
        return float(value)


class InitialParseRequest(BaseModel):
    """
    Initial parse for the Book Recommender: extract system_goals with confidence,
    and separate small_talk and out_of_scope from in-domain requests.
    """

    small_talk: Optional[str] = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        description="Small talk in the request",
    )
    out_of_scope: Optional[str] = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        description="Out-of-domain content",
    )
    system_goals: list[SystemGoal] = Field(
        default_factory=list,
        max_length=MAX_SYSTEM_GOALS,
        description="System goals for the query",
    )
    reasoning: str = Field(
        ...,
        min_length=MIN_STRING_LENGTH,
        max_length=MAX_STRING_LENGTH,
        description="Reasoning for classification",
    )

    @field_validator("small_talk", mode="before")
    @classmethod
    def check_small_talk(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        if len(value) > MAX_STRING_LENGTH:
            return value[: MAX_STRING_LENGTH - 4] + "..."
        return value

    @field_validator("out_of_scope", mode="before")
    @classmethod
    def check_out_of_scope(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        if len(value) > MAX_STRING_LENGTH:
            return value[: MAX_STRING_LENGTH - 4] + "..."
        return value

    @field_validator("reasoning", mode="before")
    @classmethod
    def check_reasoning(cls, value):
        if not isinstance(value, str):
            return f"value is not a string; padded to meet reasoning requirements"
        if len(value) < MIN_STRING_LENGTH:
            value += (
                f" padded to meet the minimum {MIN_STRING_LENGTH} character reasoning requirement"
            )
        if len(value) > MAX_STRING_LENGTH:
            return value[: MAX_STRING_LENGTH - 4] + "..."
        return value

    @field_validator("system_goals", mode="before")
    @classmethod
    def check_system_goals(cls, value):
        if not isinstance(value, list):
            value = [value]
        if len(value) > MAX_SYSTEM_GOALS:
            value = value[:MAX_SYSTEM_GOALS]
        return value


class InitialParseOutput(UserFacingOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    small_talk: Optional[str] = None
    out_of_scope: Optional[str] = None
    reasoning: Optional[str] = None

    def to_summary(self) -> dict[str, str | bool | None]:
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

    def to_llm_messages(self) -> list[AssistantMessage]:
        payload = {}
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


class InitialParseWorkflow(UserFacingBaseWorkflow[InitialParseOutput]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    ui_loading_message = "Thinking..."

    tool_models = [InitialParseRequest]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient, messages=None
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

        system_prompt = format_prompt(
            prompt_path=INITIAL_SYSTEM_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=format_node_type_catalog(),
        )
        req = OpenAIParserRequest(
            prompt=system_prompt,
            messages=[self.user_message],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req)
        tool_call = assistant_msg.tool_calls[0]
        parse_result = tool_call.function.parsed_arguments

        self.process_parse_result(parse_result)
        await self.finalize_result()
        await self.generate_user_response()

    async def finalize_result(self) -> None:
        super().finalize_result(ok=bool(self.output.accepted_goals))

    async def generate_user_response(self) -> None:
        payload = self.output.to_llm_messages()
        if not payload:
            return
        
        messages = [AssistantMessage(content=json.dumps(payload))]
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

        for goal in parse_result.system_goals:
            reasons = []
            if goal.confidence < confident_tuning:
                reasons.append(f"Rejected: confidence too low ({goal.confidence})")
            if goal.target_node_type.value not in NODE_TYPE_TO_CLS.keys():
                reasons.append(f"Rejected: target node type not supported ({goal.target_node_type})")
            if reasons or goal._refusal:
                goal.refuse(*reasons)
                self.output.refused_goals.append(goal)
            elif len(self.output.accepted_goals) < MAX_SYSTEM_GOALS:
                self.output.accepted_goals.append(goal)
            else:
                self.output.buffer_goals.append(goal)