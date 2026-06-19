from dataclasses import dataclass

from typing import List, Union

from pydantic import BaseModel, Field

from app.common.messages import AssistantMessage, UserMessage, ToolMessage
from app.common.prompt_loader import format_prompt
from app.common.sse_stream import SSEStream
from app.domains.registry import REQUEST_CLASSES
from clients.openai_client import OpenAIClient
from clients import OpenAIParserRequest
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from config import BookConstraints, BookGuides


class StrategyClassificationResult(BaseModel):
    """Generic classification result for any node type."""

    accepted: List[Union[REQUEST_CLASSES]] = []
    refused: List[Union[REQUEST_CLASSES]] = []
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
    """
    Generate a set of strategy requests to satisfy the user's request.
    Each strategy should represent a discrete unit of work.
    """

    strategies: List[Union[REQUEST_CLASSES]] = Field(
        ...,
        min_length=1,
        max_length=15,
        description="List of strategies generated from the query",
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Reasoning for strategy classification",
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


class StrategyClassificationWorkflow(
    UserFacingBaseWorkflow[StrategyClassificationOutput]
):
    success_message = "Strategy classification completed successfully"
    failure_message = "Strategy classification failed"
    ui_loading_message = "Strategizing way to complete goals..."

    _SYSTEM_PROMPT_PATH = "orchestration/planner/prompts/2_strategy_classification.txt"

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

    async def run(self, system_goals: str) -> None:
        """Classify the user query into book-related strategies."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        system_prompt = format_prompt(
            prompt_path=self._SYSTEM_PROMPT_PATH,
            book_constraints=str(BookConstraints()),
            book_guides=str(BookGuides()),
        )
        req = OpenAIParserRequest(
            prompt=system_prompt,
            messages=[AssistantMessage(content=system_goals)],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req)

        tool_message = await self.run_tool_call(assistant_msg.tool_calls[0])
        classification_result = StrategyClassificationResult.model_validate(
            tool_message.content
        )
        self.finalize_result(classification_result)

    def finalize_result(
        self, classification_result: StrategyClassificationResult
    ) -> None:
        self.output.strategy_result = classification_result
        self.output.summary = classification_result.to_summary()
        super().finalize_result(
            ok=bool(
                classification_result.continue_pipeline
                and len(classification_result.accepted) > 0
                and classification_result.get_accepted_node_ids()
            )
        )
