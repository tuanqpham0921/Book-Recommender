import logging

from app.common.prompt_loader import load_prompt

from app.common.sse_stream import SSEStream
from clients import OpenAIParserRequest

from common.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient

from typing import Optional
from pydantic import BaseModel, Field
from app.common.messages import AssistantMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)


class InitialParseBase(BaseModel):
    user_query: str = Field(
        ...,
        description="Original user query",
    )
    small_talk: Optional[str] = Field(None, description="Small talk in the request")
    out_of_scope: Optional[str] = Field(None, description="Out-of-domain content")
    user_query_domain: Optional[str] = Field(
        None, description="In-domain content (books/projects)"
    )
    reasoning: Optional[str] = Field(None, description="Reasoning for classification")


class InitialParseResult(InitialParseBase):
    continue_pipeline: bool = Field(
        default=False, description="Should the pipeline continue?"
    )

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

    # model_config = ConfigDict(json_schema_extra=_examples)

    async def __call__(self, confident_tuning: float = 0.5) -> InitialParseResult:
        return InitialParseResult(
            **self.model_dump(exclude={"domain_confidence"}),
            continue_pipeline=(
                self.domain_confidence >= confident_tuning
                and bool(self.user_query_domain)
            ),
        )


class InitialParseWorkflow(Workflow[InitialParseResult]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"

    system_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_system.txt"
    )
    user_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_parse_response.txt"
    )

    output_schema = InitialParseResult
    tool_models = [InitialParseNode]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(output_type=self.output_schema)

        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client

    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")

        # Use pipeline conversation for internal LLM calls
        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[self.user_message],
            tool_models=self.tool_models,
        )
        llm_result = await self.run_async_step(self.llm_client.execute(req))
        assistant_msg = llm_result.output

        tool_message = await self.run_async_step(
            ToolMessage.execute(assistant_msg.tool_calls[0])
        )

        parse_result = InitialParseResult.model_validate(tool_message.output.content)

        self.result.output = parse_result
        self.result.ok = bool(
            parse_result.continue_pipeline and parse_result.user_query_domain
        )
        self.result.message = (
            self.success_message if self.result.ok else self.failure_message
        )

        await self.generate_user_response(
            parse_result.to_llm_messages(),
            prompt=self.user_prompt,
            sse_stream=self.sse_stream,
        )
