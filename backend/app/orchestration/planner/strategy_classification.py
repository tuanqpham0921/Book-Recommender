from typing import List

from pydantic import BaseModel, Field

from app.common.messages import AssistantMessage, UserMessage
from app.common.prompt_loader import format_prompt
from app.common.sse_stream import SSEStream
from app.domains.books.schemas import ClassificationStrategy
from clients.openai_client import OpenAIClient
from clients import OpenAIParserRequest
from common.workflow import Workflow
from config import BookConstraints, BookGuides
from common.operation import run_tool_call


class StrategyClassificationResult(BaseModel):
    """Generic classification result for any node type."""

    accepted: List[ClassificationStrategy] = []
    refused: List[ClassificationStrategy] = []
    continue_pipeline: bool = False

    def get_accepted_node_ids(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.accepted}


class StrategyClassificationNode(BaseModel):
    """Classification node specifically for book domain strategies."""

    strategies: List[ClassificationStrategy] = Field(
        ..., max_length=15, description="List of strategies generated from the query"
    )

    async def __call__(self, accepted_tuning: float = 0.7):
        """Convert to ClassificationResult format"""
        result = StrategyClassificationResult()

        for strategy in self.strategies:
            if strategy.refusal or strategy.confidence < accepted_tuning:
                result.refused.append(strategy)
            else:
                result.accepted.append(strategy)

        result.continue_pipeline = bool(len(result.accepted) > 0)
        return result


class StrategyClassificationWorkflow(Workflow[StrategyClassificationResult]):
    success_message = "Strategy classification completed successfully"
    failure_message = "Strategy classification failed"
    ui_loading_message = "Classifying user query..."

    system_prompt = format_prompt(
        prompt_path="orchestration/planner/prompts/strategy_classification.txt",
        book_constraints=str(BookConstraints()),
        book_guides=str(BookGuides()),
    )

    tool_models = [StrategyClassificationNode]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(output_type=StrategyClassificationResult)
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client

    async def run(self, in_domain_message: str) -> StrategyClassificationResult:
        """Classify the user query into book-related strategies."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[AssistantMessage(content=in_domain_message)],
            tool_models=self.tool_models,
        )
        llm_result = await self.run_async_step(self.llm_client.execute(req))

        assistant_msg = llm_result.output

        tool_message = await self.run_async_step(
            run_tool_call(assistant_msg.tool_calls[0])
        )

        classification_result = tool_message.output
        self.result.output = classification_result
        self.result.ok = bool(
            classification_result.continue_pipeline
            and not classification_result.refused
        )
        self.result.message = (
            self.success_message if self.result.ok else self.failure_message
        )
