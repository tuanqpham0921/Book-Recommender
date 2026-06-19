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
from app.orchestration.planner.parse_intent import SystemGoal
import logging
import json
logger = logging.getLogger(__name__)
MAX_GOALS = 15

StrategyType = Union[REQUEST_CLASSES]

class StrategyClassificationResult(BaseModel):
    """Generic classification result for any node type."""

    accepted: List[StrategyType] = []
    refused: List[StrategyType] = []
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
    The strategies should be a list of the request classes in the REQUEST_CLASSES tuple.
    """

    strategies: List[StrategyType] = Field(
        default_factory=list,
        max_length=15,
        description="List of strategies generated from the query",
    )

    async def __call__(self, accepted_tuning: float = 0.7):
        """Convert to ClassificationResult format"""
        result = StrategyClassificationResult()

        for strategy in self.strategies:
            if (strategy.refusal or 
                strategy.confidence < accepted_tuning or 
                not strategy.target_goal):
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

    async def run(self, system_goals: list[SystemGoal]) -> None:
        """Classify the user query into book-related strategies."""
        if not system_goals:
            raise ValueError("System goals are required")
        
        await self.sse_stream.send_ui_loading(self.ui_loading_message)
        
        system_prompt = format_prompt(
            prompt_path=self._SYSTEM_PROMPT_PATH,
            book_constraints=str(BookConstraints()),
            book_guides=str(BookGuides()),
        )
        req = OpenAIParserRequest(
            prompt=system_prompt,
            messages=[self._format_system_goals(system_goals)],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req, save_payload=True)

        tool_message = await self.run_tool_call(assistant_msg.tool_calls[0])
        classification_result = StrategyClassificationResult.model_validate(
            tool_message.content
        )
        self.finalize_result(classification_result)
    
    def _format_system_goals(self, system_goals: list[SystemGoal]) -> AssistantMessage:
        payload = [
            {
                "id": goal.id,
                "description": goal.description,
                "confidence": goal.confidence,
            }
            for goal in system_goals
        ]
        return AssistantMessage(content=json.dumps(payload))
        
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
