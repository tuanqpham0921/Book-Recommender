import logging

from dataclasses import dataclass

from app.common.prompt_loader import load_prompt

from app.common.sse_stream import SSEStream
from clients import OpenAIParserRequest

from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient

from typing import Optional
from pydantic import BaseModel, Field
from app.common.messages import AssistantMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)


class InitialParseBase(BaseModel):
    small_talk: Optional[str] = Field(None, 
                                      min_length=50,
                                      max_length=500,
                                      description="Small talk in the request")
    out_of_scope: Optional[str] = Field(None, 
                                        min_length=50,
                                        max_length=500,
                                        description="Out-of-domain content")
    user_query_domain: Optional[str] = Field(
        None, 
        min_length=10,
        max_length=500,
        description="In-domain content for our system"
    )
    reasoning: Optional[str] = Field(None, 
                                     min_length=10,
                                     max_length=500,
                                     description="Reasoning for classification")


class InitialParseResult(InitialParseBase):
    continue_pipeline: bool = Field(
        default=False, description="Should the pipeline continue?"
    )

    def to_summary(self) -> dict[str, str | bool | None]:
        return {
            "continue_pipeline": self.continue_pipeline,
            "intent": self._infer_intent(),
            "query": self.user_query_domain or self.user_query,
            "reasoning": self.reasoning,
        }

    def _infer_intent(self) -> str:
        if self.out_of_scope:
            return "out_of_scope"
        if self.small_talk and not self.user_query_domain:
            return "small_talk"
        if not self.continue_pipeline:
            return "unknown"

        query = (self.user_query_domain or self.user_query or "").lower()
        if any(
            phrase in query
            for phrase in ("similar", "recommend", "suggest", "like these", "like this")
        ):
            return "book_recommendation"
        if any(phrase in query for phrase in ("compare", "versus", " vs ", "difference")):
            return "book_comparison"
        return "book_query"

    def to_llm_messages(self) -> list[BaseMessage]:
        return [
            AssistantMessage(
                content=self.model_dump_json(
                    include={"small_talk", "out_of_scope", "continue_pipeline"}
                )
            )
        ]


class InitialParseNode(InitialParseBase):
    domain_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence between 0 and 1 that query is domain-related",
    )

    async def __call__(self, confident_tuning: float = 0.5) -> InitialParseResult:
        return InitialParseResult(
            **self.model_dump(exclude={"domain_confidence"}),
            continue_pipeline=(
                self.domain_confidence >= confident_tuning
                and bool(self.user_query_domain)
            ),
        )


@dataclass(slots=True)
class InitialParseOutput(UserFacingOutput):
    parse_result: InitialParseResult | None = None


class InitialParseWorkflow(UserFacingBaseWorkflow[InitialParseOutput]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"

    system_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_system.txt"
    )
    user_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_parse_response.txt"
    )

    tool_models = [InitialParseNode]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=InitialParseOutput,
        )
        self.user_message = user_message

    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")

        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[self.user_message],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req)

        tool_message = await self.run_tool_call(assistant_msg.tool_calls[0])
        parse_result = InitialParseResult.model_validate(tool_message.content)

        await self.generate_user_response(
            parse_result.to_llm_messages(),
            prompt=self.user_prompt,
        )
        self.finalize_result(parse_result)
        
        
    def finalize_result(self, parse_result: InitialParseResult) -> None:
        self.output.parse_result = parse_result
        self.output.summary = parse_result.to_summary()
        super().finalize_result(
            ok=bool(parse_result.continue_pipeline and parse_result.user_query_domain)
        )
