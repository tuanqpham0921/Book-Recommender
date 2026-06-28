import json
import logging
from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from app.common.messages import AssistantMessage, UserMessage
from app.common.prompt_loader import format_prompt
from app.common.sse_stream import SSEStream
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.domains.base_request import BaseRequest
from app.domains.registry import (
    BOOK_ANALYZE_CLASSES,
    BOOK_RETRIEVAL_CLASSES,
    NODE_TYPE_TO_CLS,
)
from app.domains.planner.parse_intent import SystemGoal
from clients import OpenAIParserRequest
from clients.openai_client import OpenAIClient
from common.utils import uuid_8
from config import BookConstraints, BookGuides


logger = logging.getLogger(__name__)

MAX_STRATEGIES = 15

class StrategyRequest(BaseModel):
    """
    Generate a set of strategy requests to satisfy the user's request.
    Each strategy should represent a discrete unit of work.
    The strategies should be a list of the request classes in the REQUEST_CLASSES tuple.
    """

    strategies: list[BaseRequest] = Field(
        default_factory=list,
        max_length=MAX_STRATEGIES,
        description="List of strategies generated from the query",
    )

    @classmethod
    def build_model(
        cls,
        strategy_types: list[type[BaseModel]],
    ) -> type[BaseModel]:
        if not strategy_types:
            logger.warning("No strategy types provided, returning base model")
            return cls

        strategy_union = reduce(or_, strategy_types)

        return create_model(
            "StrategyRequest",
            __config__=ConfigDict(
                title="StrategyRequest",
                description=cls.__doc__,
            ),
            strategies=(
                list[strategy_union],
                Field(
                    default_factory=list,
                    max_length=MAX_STRATEGIES,
                    description="List of strategies generated from the query",
                ),
            ),
        )

    @field_validator("strategies", mode="before")
    @classmethod
    def check_strategies(cls, value):
        if not isinstance(value, list):
            value = [value]

        seen_ids: set[str] = set()
        deduped = []
        for item in value:
            item_id = (
                item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            )
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            deduped.append(item)

        return deduped[:MAX_STRATEGIES]


@dataclass(slots=True)
class StrategyClassificationOutput(UserFacingOutput):
    accepted: list[BaseRequest] = field(default_factory=list)
    refused: list[BaseRequest] = field(default_factory=list)
    buffer: list[BaseRequest] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, bool | int | list[str]]:
        return {
            "strategy_ids": [strategy.id for strategy in self.accepted],
        }

    def get_accepted_id_to_node(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.accepted}


class StrategyClassificationWorkflow(
    UserFacingBaseWorkflow[StrategyClassificationOutput]
):
    success_message = "Strategy classification completed successfully"
    failure_message = "Strategy classification failed"
    ui_loading_message = "Strategizing..."

    _SYSTEM_PROMPT_PATH = "domains/planner/prompts/2_strategy_classification.txt"

    tool_models = [StrategyRequest]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient, messages=None
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=StrategyClassificationOutput,
            messages=messages,
        )
        self.user_message = user_message

    async def run(
        self, user_message: UserMessage, system_goals: list[SystemGoal]
    ) -> None:
        """Classify the user query into book-related strategies."""
        if not system_goals:
            raise ValueError("System goals are required")

        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        system_prompt = format_prompt(
            prompt_path=self._SYSTEM_PROMPT_PATH,
            book_constraints=str(BookConstraints()),
            book_guides=str(BookGuides()),
        )
        strategy_request = self.build_strategy_request(system_goals)
        req = OpenAIParserRequest(
            prompt=system_prompt,
            # TODO: I think there's a warning here
            messages=[self.user_message, self._format_system_goals(system_goals)],
            tool_models=[strategy_request],
        )
        assistant_msg = await self.run_llm_call(req)
        tool_call = assistant_msg.tool_calls[0]
        parse_result = tool_call.function.parsed_arguments

        llm_to_internal_id = self.set_llm_id(parse_result.strategies)
        self.map_dependencies_to_internal_ids(parse_result.strategies, llm_to_internal_id)
        self.process_classification_result(parse_result.strategies, system_goals)
        self.create_execution_order()
        self.finalize_result()
        
    def set_llm_id(self, strategies: list[BaseRequest]) -> None:
        llm_to_internal_id = {}
        for strategy in strategies:
            llm_id = strategy.id
            strategy._llm_id = llm_id
            strategy.id = f"task_{uuid_8()}"
            llm_to_internal_id[llm_id] = strategy.id
        return llm_to_internal_id

    def map_dependencies_to_internal_ids(self, 
                                         strategies: list[BaseRequest], 
                                         llm_to_internal_id: dict[str, str]) -> None:
        for strategy in strategies:
            if not hasattr(strategy, "depends_on"):
                continue
            if strategy.depends_on is None:
                strategy.refuse("No dependencies provided")
                continue

            dependency_ids = []
            for dependency in strategy.depends_on:
                if dependency in llm_to_internal_id:
                    dependency_ids.append(llm_to_internal_id[dependency])
                else:
                    strategy.refuse(f"Dependency {dependency} not found")
                    break
            strategy.depends_on = dependency_ids

    def build_strategy_request(self, system_goals: list[SystemGoal]) -> StrategyRequest:
        request_classes = set()
        for goal in system_goals:
            if goal.target_node_type.value in NODE_TYPE_TO_CLS:
                node_cls = NODE_TYPE_TO_CLS[goal.target_node_type.value]
                request_classes.add(node_cls)

        self._inject_book_request_classes(request_classes)
        return StrategyRequest.build_model(tuple(request_classes))

    def _inject_book_request_classes(
        self, request_classes: set[type[BaseModel]]
    ) -> None:
        """Best effort to inject missing request classes to the request classes set."""
        inject_classes = set()
        for request_cls in request_classes:
            # if analyze class is present, there should be at least one retrieval class
            if request_cls in BOOK_ANALYZE_CLASSES:
                retrieval_cls = [
                    cls for cls in request_classes if cls in BOOK_RETRIEVAL_CLASSES
                ]
                if not retrieval_cls:
                    logger.warning(
                        f"No retrieval class for analyze class. Injecting all retrieval classes."
                    )
                    inject_classes.update(BOOK_RETRIEVAL_CLASSES)

        request_classes.update(inject_classes)

    def _format_system_goals(self, system_goals: list[SystemGoal]) -> AssistantMessage:
        payload = [
            {
                "id": goal.id,
                "description": goal.description,
            }
            for goal in system_goals
        ]
        return AssistantMessage(content=json.dumps(payload))

    def process_classification_result(
        self,
        strategies: list[BaseRequest],
        system_goals: list[SystemGoal],
        accepted_tuning: float = 0.7,
    ):
        """Convert to ClassificationResult format"""
        accepted_goals_ids = {goal.id for goal in system_goals}

        for strategy in strategies:
            reasons = []
            missing_goals = [g for g in strategy.target_goal if g not in accepted_goals_ids]
            if missing_goals:
                reasons.append(f"Missing target goals: {missing_goals}")
            elif not strategy.target_goal:
                reasons.append("No target goals provided")
            if strategy.confidence < accepted_tuning:
                reasons.append(f"Confidence {strategy.confidence} below accepted tuning")
            
            if reasons or strategy._refusal:
                strategy.refuse(*reasons)
                self.output.refused.append(strategy)
            elif len(self.output.accepted) < MAX_STRATEGIES:
                self.output.accepted.append(strategy)
            else:
                self.output.buffer.append(strategy)

    def get_strategies_ids(self, strategies: list[BaseRequest]) -> list[str]:
        return set(strategy.id for strategy in strategies)

    def finalize_result(self) -> None:
        super().finalize_result(
            ok=bool(self.output.execution_order and self.output.accepted)
        )

    def create_execution_order(self) -> list[str]:
        # Build adjacency list and indegree map
        from collections import defaultdict, deque

        tasks = self.output.accepted

        graph = defaultdict(list)
        indegree = defaultdict(int)

        for task in tasks:
            task_id = task.id
            if not hasattr(task, "depends_on"):
                indegree[task_id] = 0
                continue
            
            for dep in task.depends_on:
                graph[dep].append(task_id)
                indegree[task_id] += 1
        
        # Start with nodes that have no dependencies
        queue = deque([t for t, d in indegree.items() if d == 0])
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in graph[node]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)

        self.output.execution_order = order
        if order:
            logger.info(
                f"📋 Task execution order: {' -> '.join(order) if order else 'No tasks'}"
            )
        else:
            logger.warning("No execution order created")
        
        # Check for cycles in the dependency graph
        if len(order) != len(indegree):
            self._remove_cycles(indegree)
            
    def _remove_cycles(self, indegree: dict[str, int]) -> None:
        """Remove cycles from the dependency graph"""
        excepted_nodes = self.output.get_accepted_id_to_node()
        logger.warning("Cycle detected in dependency graph")
        remaining_nodes = [node_id for node_id, degree in indegree.items() if degree > 0]
        for node_id in remaining_nodes:
            logger.warning(f"Removing node {node_id} from accepted list")
            if node_id not in excepted_nodes:
                continue
            node = excepted_nodes[node_id]
            self.output.accepted.remove(node)
            excepted_nodes.pop(node_id, None)
            node._refusal = True
            node._refusal_reasons.append("Cycle detected in dependency graph")
            self.output.refused.append(node)