import json
import logging
from typing import Any
from functools import reduce
from operator import or_
from collections import defaultdict, deque
from pydantic import BaseModel, Field, PrivateAttr, create_model, model_validator, ValidationError
from openai.types.chat import ParsedFunctionToolCall
from app.common.messages import AssistantMessage, ToolMessage, UserMessage
from app.common.prompt_loader import format_prompt
from app.common.sse_stream import SSEStream
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.domains.base_request import BaseRequest
from app.domains.registry import (
    BOOK_ANALYZE_CLASSES,
    BOOK_RETRIEVAL_CLASSES,
    NODE_TYPE_TO_CLS,
    AnyStrategyRequest,
)
from app.domains.planner.parse_intent import SystemGoal
from clients import OpenAIParserRequest
from clients.openai_client import OpenAIClient
from common.utils import uuid_8
from config import BookConstraints, BookGuides


logger = logging.getLogger(__name__)

STRATEGY_CLASSIFICATION_PROMPT_PATH = "domains/planner/prompts/2_strategy_classification.txt"

MAX_STRATEGIES = 15

class StrategyRequest(BaseModel):
    """
    Generate a set of strategy requests to satisfy the user's request.
    Each strategy should represent a discrete unit of work.
    The strategies should be a list of the request classes in the REQUEST_CLASSES tuple.
    """

    strategies: list[AnyStrategyRequest] = Field(
        default_factory=list,
        max_length=MAX_STRATEGIES,
        description="List of strategies generated from the query",
    )
    
    # invisible to LLM output
    # internal use only
    _overflow_strategies: list = PrivateAttr(default_factory=list)
    _invalid_strategies: list = PrivateAttr(default_factory=list)

    @classmethod
    def build_model(
        cls,
        strategy_types: list[type[BaseModel]],
    ) -> type[BaseModel]:
        if not strategy_types:
            raise TypeError("No strategy types provided")

        strategy_union = reduce(or_, strategy_types)

        return create_model(
            "StrategyRequest",
             __base__=StrategyRequest,
            strategies=(
                list[strategy_union],
                Field(
                    default_factory=list,
                    max_length=MAX_STRATEGIES,
                    description="List of strategies generated from the query",
                ),
            ),
        )

    @model_validator(mode='wrap')
    @classmethod
    def capture_and_filter(cls, data, handler):
        raw = data.get('strategies', []) if isinstance(data, dict) else []
        if not isinstance(raw, list):
            raw = [raw]

        valid, invalid = [], []
        for item in raw:
            if isinstance(item, BaseRequest):
                valid.append(item)
            elif isinstance(item, dict):
                try:
                    BaseRequest.model_validate(item)
                    valid.append(item)
                except ValidationError:
                    invalid.append(item)
            else:
                invalid.append(item)
        
        if isinstance(data, dict):
            data['strategies'] = valid[:MAX_STRATEGIES]
        
        instance = handler(data)  # Pydantic builds the instance
        instance._overflow_strategies = valid[MAX_STRATEGIES:]
        instance._invalid_strategies = invalid
        return instance


class StrategyClassificationOutput(UserFacingOutput):
    accepted: list[AnyStrategyRequest] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)

    # NOTE: this can be private or not?
    # for retries, continuation, or summaries
    buffer: list[AnyStrategyRequest] = Field(default_factory=list)
    refused: list[AnyStrategyRequest] = Field(default_factory=list)

    invalid: list[Any] = Field(default_factory=list)
    
    def to_summary(self) -> dict[str, bool | int | list[str]]:
        return {
            "strategy_ids": [strategy.id for strategy in self.accepted],
        }

    def get_accepted_id_to_node(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.accepted}
    
    def get_refused_id_to_node(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.refused}


class StrategyClassificationWorkflow(
    UserFacingBaseWorkflow[StrategyClassificationOutput]
):
    success_message = "Strategy classification completed successfully"
    failure_message = "Strategy classification failed"
    ui_loading_message = "Strategizing..."

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

        tool_call = await self._run_llm_args_parse(system_goals)
        parse_result = tool_call.function.parsed_arguments
        if parse_result._invalid_strategies:
            logger.warning(f"LLM created {len(parse_result._invalid_strategies)} invalid strategies")
            self.output.invalid = parse_result._invalid_strategies
        
        if parse_result._overflow_strategies:
            logger.warning(f"LLM created {len(parse_result._overflow_strategies)} overflow strategies")
        
        all_strategies = parse_result.strategies + parse_result._overflow_strategies
        # assign and validate ids
        llm_to_internal_id = self._set_llm_id(all_strategies)
        self._map_dependencies_to_internal_ids(all_strategies, llm_to_internal_id)
 
        # process the goals and confidence
        id_to_node = {task.id:task for task in all_strategies}
        candidates = self._get_candidates(all_strategies, system_goals)
        
        # topological sort and remove bad nodes
        graph, indegree = self._get_graph_indegree(candidates)
        order = self._create_execution_order(graph, indegree, id_to_node)
        
        self._add_to_accepted(order, id_to_node)
        self.output.execution_order = [strat.id for strat in self.output.accepted]
        
        self.finalize_result(tool_call)
    
    async def _run_llm_args_parse(self, system_goals: list[SystemGoal]) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=STRATEGY_CLASSIFICATION_PROMPT_PATH,
            book_constraints=str(BookConstraints()),
            book_guides=str(BookGuides()),
        )
        strategy_request = self._build_strategy_request(system_goals)
        req = OpenAIParserRequest(
            prompt=system_prompt,
            # TODO: I think there's a warning here
            messages=[self.user_message, self._format_system_goals(system_goals)],
            tool_models=[strategy_request],
        )
        assistant_msg = await self.run_llm_call(req)
        tool_call = assistant_msg.tool_calls[0]
        return tool_call
    
    def _build_strategy_request(self, system_goals: list[SystemGoal]) -> StrategyRequest:
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
        
    def _set_llm_id(self, strategies: list[BaseRequest]) -> dict[str, str]:
        llm_to_internal_id = {}
        for strategy in strategies:
            llm_id = strategy.id
            if llm_id in llm_to_internal_id:
                # create new one so tasks depends on this gets refused
                llm_id = f"task_{uuid_8()}"
                strategy.add_details("duplicate llm_id, created a new one")
                
            strategy._llm_id = llm_id
            strategy.id = f"task_{uuid_8()}"
            llm_to_internal_id[llm_id] = strategy.id
        
        return llm_to_internal_id

    def _map_dependencies_to_internal_ids(self, 
                                         strategies: list[BaseRequest], 
                                         llm_to_internal_id: dict[str, str]) -> None:
        for strategy in strategies:
            if not hasattr(strategy, "depends_on"):
                continue
            if strategy.depends_on is None or not len(strategy.depends_on):
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

    def _get_candidates(
        self,
        strategies: list[BaseRequest],
        system_goals: list[SystemGoal],
        accepted_tuning: float = 0.7,
    ) -> list[BaseRequest]:
        """Validate confidence and goals ids"""
        accepted_goals_ids = {goal.id for goal in system_goals}
        pass_strategies = []
        for strategy in strategies:
            missing_goals = [g for g in strategy.target_goal if g not in accepted_goals_ids]
            if missing_goals:
                strategy.refuse(f"Missing target goals: {missing_goals}")
            elif not strategy.target_goal:
                strategy.refuse("No target goals provided")
            
            if strategy.confidence < accepted_tuning:
                strategy.refuse(f"Confidence {strategy.confidence} below accepted tuning")
            
            if strategy.refusal:
                self.output.refused.append(strategy)
            else:
                pass_strategies.append(strategy)
        
        return pass_strategies
            
    def _get_graph_indegree(
        self, candidates: list[BaseRequest]
    ) -> tuple[defaultdict[str, list[str]], defaultdict[str, int]]:
        """ create the graph and indegree """
        graph = defaultdict(list)
        indegree = defaultdict(int)
        for task in candidates:
            task_id = task.id
            if not hasattr(task, "depends_on"):
                indegree[task_id] = 0
                continue
            
            for dep in task.depends_on:
                graph[dep].append(task_id)
                indegree[task_id] += 1
                
        return graph, indegree

    def _create_execution_order(
        self,
        graph: defaultdict[str, list[str]],
        indegree: defaultdict[str, int],
        id_to_node: dict[str, BaseRequest],
    ) -> list[str]:
        # Build adjacency list and indegree map
        order = self._sort_graph(graph, indegree)
        
        # Check for cycles in the dependency graph
        if len(order) != len(indegree):
            logger.warning("Cycle detected in dependency graph")
            remove_ids = set()
            cycle_nodes = set(indegree) - set(order)
            for cycle_node in cycle_nodes:
                self._remove_cycles(graph, cycle_node, remove_ids, id_to_node)

            order = [id for id in order if id not in remove_ids]
        
        return order    
    
    def _sort_graph(
        self,
        graph: defaultdict[str, list[str]],
        indegree: defaultdict[str, int],
    ) -> list[str]:
        """ Sort the graph and return the indegree"""
        
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
        return order
            
    def _remove_cycles(
        self,
        graph: defaultdict[str, list[str]],
        cur: str,
        remove_ids: set[str],
        id_to_node: dict[str, BaseRequest],
    ) -> None:
        """Remove cycles from the dependency graph"""
        if cur in remove_ids:
            return
        
        # refuse this node
        remove_ids.add(cur)
        node = id_to_node[cur]
        node.refuse("In graph cycle path")
        self.output.refused.append(node)
        
        # all the nodes depends on this
        for nei in graph[cur]:
            self._remove_cycles(graph, nei, remove_ids, id_to_node)
        
            
    def _add_to_accepted(self, order: list[str], id_to_node: dict[str, BaseRequest]) -> None:
        """ Add as mainly low level as possible for parrallelism"""
        for id in order:
            node = id_to_node[id]
            if len(self.output.accepted) < MAX_STRATEGIES:
                self.output.accepted.append(node)
            else:
                node.add_details("Waiting over limit, waiting")
                self.output.buffer.append(node)        
        
    def finalize_result(self, tool_call: ParsedFunctionToolCall) -> None:
        # NOTE: here you can do output.validate?
        self.messages.append(
            ToolMessage(
                name=tool_call.function.name,
                tool_call_id=tool_call.id,
                content=self.output,
            )
        )
        super().finalize_result(
            ok=bool(self.output.accepted)
        )