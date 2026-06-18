from dataclasses import dataclass

from typing import List

from pydantic import BaseModel, Field

from app.common.messages import AssistantMessage, UserMessage, ToolMessage
from app.common.prompt_loader import format_prompt
from app.common.sse_stream import SSEStream
from app.domains import AllRequests
from clients.openai_client import OpenAIClient
from clients import OpenAIParserRequest
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from config import BookConstraints, BookGuides


class StrategyClassificationResult(BaseModel):
    """Generic classification result for any node type."""

    accepted: List[AllRequests] = []
    refused: List[AllRequests] = []
    continue_pipeline: bool = False

    def get_accepted_node_ids(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.accepted}

    def to_summary(self) -> dict[str, bool | int | list[str]]:
        return {
            "continue_pipeline": self.continue_pipeline,
            "accepted_count": len(self.accepted),
            "refused_count": len(self.refused),
            "strategy_ids": [strategy.id for strategy in self.accepted],
        }


class StrategyClassificationNode(BaseModel):
    """Classification node specifically for book domain strategies."""

    strategies: List[AllRequests] = Field(
        ...,
        min_length=1,
        max_length=15,
        description="List of strategies generated from the query"
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Reasoning for strategy classification"
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


@dataclass(slots=True)
class StrategyClassificationOutput(UserFacingOutput):
    strategy_result: StrategyClassificationResult | None = None


class StrategyClassificationWorkflow(UserFacingBaseWorkflow[StrategyClassificationOutput]):
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
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=StrategyClassificationOutput,
        )
        self.user_message = user_message

    async def run(self, in_domain_message: str) -> None:
        """Classify the user query into book-related strategies."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[AssistantMessage(content=in_domain_message)],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req)

        tool_message = await self.run_tool_call(assistant_msg.tool_calls[0])
        classification_result = StrategyClassificationResult.model_validate(
            tool_message.content
        )
        self.finalize_result(classification_result)

    def finalize_result(self, classification_result: StrategyClassificationResult) -> None:
        self.output.strategy_result = classification_result
        self.output.summary = classification_result.to_summary()
        super().finalize_result(
            ok=bool(
                classification_result.continue_pipeline
                and len(classification_result.accepted) > 0
                and classification_result.get_accepted_node_ids()
            )
        )