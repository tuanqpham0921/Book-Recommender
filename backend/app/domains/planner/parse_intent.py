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

logger = logging.getLogger(__name__)

GOAL_GENERATOR_PROMPT_PATH = "domains/planner/prompts/0_goal_generator.txt"
INITIAL_PARSE_RESPONSE_PROMPT_PATH = (
    "domains/planner/prompts/1_initial_parse_response.txt"
)
INTENT_PARSER_PROMPT_PATH = "domains/planner/prompts/0_intent_parser.txt"

MAX_SYSTEM_GOALS = 10


class SystemGoal(BaseModel):
    """Purpose: One parsed goal from the user's message — a capability the
    system should attempt, with the confidence that it maps cleanly to a
    supported node type. One entry in GoalParseRequest.system_goals.

    Args:
        description: A concise, instructive description of the goal (10-100 characters).
        confidence: How confident the system is that it can fulfill this goal
        target_node_type: The single capability name from the catalog that
            fulfills this goal.

    Returns: One candidate goal that strategy classification later turns
    into a request strategy, or refuses.

    Constraints: exactly one target_node_type per goal — a multi-part
    request becomes separate goals, not one goal with multiple types.
    """

    node_type: Literal[PlannerNodeTypeEnum.SYSTEM_GOAL] = (
        PlannerNodeTypeEnum.SYSTEM_GOAL
    )

    description: DescriptionStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "Find Dune by title"},
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


class GoalParseRequest(BaseModel):
    """Purpose: Goals parse of the user's message — the tool call for the
    parse-intent LLM step. Splits the message into system_goals (mapped
    capabilities), small_talk, and out_of_scope content.

    Args:
        small_talk: The small-talk portion of the message, when present.
        out_of_scope: The out-of-domain portion of the message, when present.
        system_goals: One SystemGoal per capability the message maps to;
            empty when nothing in-domain was found.
        reasoning: Short explanation of how the message was classified.

    Returns: The parsed breakdown that strategy classification
    (system_goals) and the response step (small_talk/out_of_scope/reasoning)
    consume next.

    Constraints: at most MAX_SYSTEM_GOALS (10) goals per call; every
    in-domain part of the message should map to exactly one goal.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "Hi! Can you recommend books like Dune?",
                    "request": {
                        "small_talk": "Hi!",
                        "system_goals": [
                            {
                                "description": "Find Dune by title",
                                "confidence": 1.0,
                                "target_node_type": "Retrieve_by_Title",
                            },
                            {
                                "description": "Recommend books similar to Dune",
                                "confidence": 1.0,
                                "target_node_type": "Analyze_Recommend",
                            },
                        ],
                        "reasoning": "Greeting plus a direct match to two supported capabilities",
                    },
                },
                {
                    "query": "What's the weather like today?",
                    "request": {
                        "system_goals": [],
                        "out_of_scope": "What's the weather like today?",
                        "reasoning": "No supported capability covers weather",
                    },
                },
                {
                    "query": "Find some sci-fi books",
                    "request": {
                        "system_goals": [
                            {
                                "description": "Find sci-fi books",
                                "confidence": 1.0,
                                "target_node_type": "Retrieve_by_Genre",
                            }
                        ],
                        "reasoning": "Direct match to a supported capability",
                    },
                },
                {
                    "query": "Compare Flights and Satantango",
                    "request": {
                        "system_goals": [
                            {
                                "description": "Find Flights",
                                "confidence": 1.0,
                                "target_node_type": "Retrieve_by_Title",
                            },
                            {
                                "description": "Find Satantango",
                                "confidence": 1.0,
                                "target_node_type": "Retrieve_by_Title",
                            },
                            {
                                "description": "Compare Flights and Satantango",
                                "confidence": 1.0,
                                "target_node_type": "Analyze_Compare",
                            },
                        ],
                        "reasoning": "Comparison requires retrieving both titles before comparing them",
                    },
                },
                {
                    "query": "What's my saved memory?",
                    "request": {
                        "system_goals": [
                            {
                                "description": "Retrieve user saved memory",
                                "confidence": 1.0,
                                "target_node_type": "Retrieve_User_Info",
                            }
                        ],
                        "reasoning": "Direct match to a supported capability",
                    },
                },
                {
                    "query": "Can you help me with calculus homework?",
                    "request": {
                        "system_goals": [],
                        "out_of_scope": "Can you help me with calculus homework?",
                        "reasoning": "No supported capability covers homework help",
                    },
                },
                {
                    "query": "that one",
                    "request": {
                        "system_goals": [],
                        "reasoning": "Ambiguous — no mappable capability",
                    },
                },
            ]
        }
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
    out_of_scope: OptionalStr = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "What's the weather like today?"},
    )

    # TODO: remove this and move the parse_intent
    small_talk: OptionalStr = Field(
        default=None,
        max_length=MAX_STRING_LENGTH,
        json_schema_extra={"example": "Hi!"},
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


class IntentParseRequest(BaseModel):
    """Purpose: Coarse pre-filter before the full intent/goal parse — flags
    malicious input and references to earlier turns (this app is
    single-turn only) so the workflow can refuse them before any planning
    work starts.

    Args:
        intents: Flags that apply to the message; empty when neither does.

    Returns: The flags the workflow uses to decide whether to continue to
    the full parse or refuse the message outright.

    Constraints: `malicious` is exclusive — never paired with
    `conversation_continuation`.
    """

    intents: list[
        Literal[
            "malicious",
            "conversation_continuation",
        ]
    ] = Field(
        default_factory=list,
        max_length=2,
        json_schema_extra={"example": []},
    )

    def model_post_init(self, context) -> None:
        self.intents = list(dict.fromkeys(self.intents))
        if "malicious" in self.intents:
            self.intents = ["malicious"]


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

        intent_tool_call = await self._run_llm_intent_request()
        intent_result = cast(
            IntentParseRequest, intent_tool_call.function.parsed_arguments
        )

        reject_reasons = self._get_intent_reject_reasons(intent_result)
        if reject_reasons:
            # TODO: these should raise errors so the caller can catch
            message = (
                self.continuation_reject_message
                if intent_result.intents == ["conversation_continuation"]
                else self.intent_reject_message
            )
            self.result.add_details(*reject_reasons)
            self.result.ok = False
            self.result.message = message
            await self.sse_stream.send_chars(message)
            return

        tool_call = await self._run_llm_args_parse()
        # parsed_arguments is typed `object | None` by the openai lib; the
        # parser validated it against GoalParseRequest, so the cast holds
        parse_result = cast(GoalParseRequest, tool_call.function.parsed_arguments)
        self.process_parse_result(parse_result)
        self._record_tool_call(tool_call)
        payload = self.output.to_llm_messages()
        await self.finalize_result(payload)
        await self.generate_user_response(payload)

    def _get_intent_reject_reasons(
        self, intent_result: IntentParseRequest
    ) -> list[str]:
        reasons = []
        if "malicious" in intent_result.intents:
            reasons.append("Rejected: malicious intent detected")
        if "conversation_continuation" in intent_result.intents:
            reasons.append("Rejected: references an earlier turn (single-turn only)")
        return reasons

    async def _run_llm_intent_request(self) -> ParsedFunctionToolCall:
        system_prompt = load_prompt(INTENT_PARSER_PROMPT_PATH)
        req = OpenAIParserRequest(
            prompt=system_prompt,
            messages=[self.user_message],
            tool_models=[IntentParseRequest],
        )
        assistant_msg = await self.run_llm_call(req)
        tool_calls = assistant_msg.tool_calls
        if not tool_calls:
            # previously an unguarded [0] on None — same failure semantics
            # (runtime error caught by the workflow), clearer message
            raise ValueError("LLM response contained no tool calls")
        return tool_calls[0]

    async def _run_llm_args_parse(self) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=GOAL_GENERATOR_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=format_node_type_catalog(),
        )
        # NOTE: using gpt4.1 because the system goals sees the whole catalog
        # it's very important that this part is done correctly
        # cache hit rate is high, and output generation is lower
        # we can optimize and move out the small_talk and such
        req = OpenAIParserRequest(
            prompt=system_prompt,
            model="gpt-4.1",
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
        self, parse_result: GoalParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if (
            len(parse_result.system_goals) == 0
            and not parse_result.small_talk
            and not parse_result.out_of_scope
        ):
            logger.warning("Nothing was classified in the initial parse")
            self.result.ok = False
            self.result.add_details("Nothing was classified in the initial parse")
            raise RuntimeError("Nothing was classified in the initial parse")

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
