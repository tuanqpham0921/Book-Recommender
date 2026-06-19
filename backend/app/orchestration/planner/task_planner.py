from __future__ import annotations
import json
import logging

from pydantic import BaseModel, Field
from typing import List

from app.domains.books.types import (
    NodeType,
    SINGLE_BOOK_RETRIEVAL,
)

from dataclasses import dataclass

from app.domains.base_request import BaseRequest
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.common.sse_stream import SSEStream
from app.common.prompt_loader import load_prompt
from app.common.messages import AssistantMessage
from clients import OpenAIParserRequest


logger = logging.getLogger(__name__)

MAX_TASKS = 10


class Task(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    depends_on: list[str] = Field(default_factory=list, max_length=5)
    refusal: bool = Field(default=False, description="Did we refuse this task?")
    reasoning: str = Field(
        ..., min_length=10, max_length=500, description="Reasoning for task creation"
    )

    def model_post_init(self, __context: object) -> None:
        """Validate the dependencies of the task and return a new task with the valid dependencies"""
        if self.id in self.depends_on:
            logger.warning(f"Task {self.id} depended on itself; removing dependency")
            self.depends_on.remove(self.id)

    def with_valid_dependencies(self, valid_ids: set[str]) -> "Task":
        """Validate the dependencies of the task and return a new task with the valid dependencies"""
        if self.id not in valid_ids:
            return self.model_copy(
                update={
                    "refusal": True,
                    "reasoning": f"Task id {self.id} is not a valid node id (internal error)",
                }
            )

        valid_deps = [dep for dep in self.depends_on if dep in valid_ids]
        invalid_deps = set(self.depends_on) - valid_ids

        if invalid_deps:
            logger.warning(f"Task {self.id} had invalid dependencies: {invalid_deps}")

        return self.model_copy(update={"depends_on": valid_deps})


class TaskPlan(BaseModel):
    model_config = {"extra": "forbid"}

    accepted: List[Task] = Field(default_factory=list)
    refused: List[Task] = Field(default_factory=list)
    missing_ids: List[str] = Field(default_factory=list)
    execution_order: List[str] = Field(default_factory=list)

    def validate_plan(self, node_ids: dict[str, BaseRequest]) -> None:
        self._validate_dependency_rules(node_ids)
        self._validate_dependency_in_accepted(node_ids)
        self.execution_order = self._create_execution_order()
        self._validate_execution_order()

    def _validate_execution_order(self) -> None:
        accepted_ids = set(task.id for task in self.accepted)
        order_ids = set(self.execution_order)
        if order_ids != accepted_ids:
            missing_ids = accepted_ids - order_ids
            extra_ids = order_ids - accepted_ids
            raise ValueError(
                f"Execution order mismatch. Missing={missing_ids}, extra={extra_ids}"
            )

    def _validate_dependency_in_accepted(
        self, node_ids: dict[str, BaseRequest]
    ) -> None:
        accepted_ids = set(task.id for task in self.accepted)
        for task in self.accepted:
            for dep in task.depends_on:
                if dep not in accepted_ids:
                    raise ValueError(
                        f"Dependency {dep} in task {task.id} is not in accepted. Accepted ids: {sorted(accepted_ids)}"
                    )

    # Here we should know that the ids are valid nodes
    def _validate_dependency_rules(self, node_ids: dict[str, BaseRequest]) -> None:
        """Enforce the rules for accepted strategies. Add to refuse if fails"""
        valid_accepted = []
        for task in self.accepted:
            node = node_ids[task.id]
            type = node.node_type

            if type is None:
                continue

            # check the dependencie rules for Retrieval and Analyze nodes
            if type in SINGLE_BOOK_RETRIEVAL and len(task.depends_on) != 0:
                logger.warning(f"⚠️ Single Book Retrieval ID {task.id} has dependencies")
                task.depends_on = []
            elif type == NodeType.COMPARE and len(task.depends_on) < 2:
                logger.warning(
                    f"⚠️ Compare Book Strategy ID {task.id} doesn't have enough dependencies"
                )
                self.refused.append(task)
                continue

            valid_accepted.append(task)

        self.accepted = valid_accepted

    def _create_execution_order(self):
        # Build adjacency list and indegree map
        from collections import defaultdict, deque

        tasks = self.accepted

        graph = defaultdict(list)
        indegree = defaultdict(int)

        for task in tasks:
            task_id = task.id
            for dep in task.depends_on:
                graph[dep].append(task_id)
                indegree[task_id] += 1
            indegree.setdefault(task_id, 0)

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

        # Check for cycles in the dependency graph
        if len(order) != len(indegree):
            remaining_nodes = [node for node, degree in indegree.items() if degree > 0]
            raise ValueError(
                f"Cycle detected in dependency graph! Nodes involved: {remaining_nodes}"
            )

        logger.info(
            f"📋 Task execution order: {' -> '.join(order) if order else 'No tasks'}"
        )

        return order

    def to_summary(self) -> dict[str, int | list[str]]:
        return {
            "task_count": len(self.accepted),
            "execution_order": self.execution_order,
            "missing_count": len(self.missing_ids),
            "refused": [task.reasoning for task in self.refused],
        }


class TaskGenerationNode(BaseModel):
    """
    Construct a dependency graph for the provided strategies.

    Determine which strategies can execute independently and which
    require outputs from other strategies. Generate the minimal set
    of dependencies required for correct execution.

    Use only the provided strategy IDs when creating dependencies.
    Avoid unnecessary dependencies that would reduce parallelism.
    """

    model_config = {"extra": "forbid"}

    tasks: List[Task] = Field(
        ...,
        description=f"Create at most {MAX_TASKS} tasks with resolved dependencies",
        max_length=MAX_TASKS,
    )

    async def __call__(self, node_ids) -> TaskPlan:
        logger.debug("🔍 Processing TaskGenerationNode")

        valid_ids = set(node_ids.keys())
        missing_ids = valid_ids.copy()
        accepted, refused, seen_ids = [], [], set()

        for task in self.tasks:
            if task.id not in valid_ids:
                logger.warning(f"⚠️ TaskGeneration hallucinated ID: {task.id}")
                continue

            if task.id in seen_ids:
                logger.warning(f"⚠️ TaskGeneration classified duplicates ID: {task.id}")
                continue

            validated_task = task.with_valid_dependencies(valid_ids=valid_ids)

            if not validated_task.refusal:
                accepted.append(validated_task)
            else:
                refused.append(validated_task)

            seen_ids.add(task.id)
            if task.id in missing_ids:
                missing_ids.remove(task.id)

        plan_result = TaskPlan(
            accepted=accepted,
            refused=refused,
            missing_ids=missing_ids,
        )

        plan_result.validate_plan(node_ids=node_ids)
        return plan_result


@dataclass(slots=True)
class TaskPlanOutput(UserFacingOutput):
    task_plan: TaskPlan | None = None


class TaskPlanWorkflow(UserFacingBaseWorkflow[TaskPlanOutput]):
    success_message = "Task plan created successfully"
    failure_message = "Task plan creation failed"
    ui_loading_message = "Creating task plan..."

    planner_failure_message = (
        "I couldn't create a task plan for your request. Please try again."
    )

    prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/dependency_resolution.txt",
    )
    tool_models = [TaskGenerationNode]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=TaskPlanOutput,
        )
        self.user_message = user_message

    async def run(self, system_goals: str, node_ids: dict[str, BaseRequest]) -> None:
        """Create a task execution plan with dependency resolution."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        if not node_ids:
            raise RuntimeError("No accepted node ids")

        tool_override = self.modify_schema(
            tool_model=self.tool_models[0], valid_ids=list(node_ids.keys())
        )

        formatted_node_ids = {}
        for id in node_ids:
            formatted_node_ids[id] = node_ids[id].model_dump()

        messages = [
            AssistantMessage(content=system_goals),
            AssistantMessage(
                content=json.dumps(formatted_node_ids, separators=(",", ":"))
            ),
        ]

        req = OpenAIParserRequest(
            prompt=self.prompt,
            messages=messages,
            tool_models=self.tool_models,
            tool_override=tool_override,
            temperature=0.4,
            top_p=0.5,
        )
        assistant_msg = await self.run_llm_call(req)
        tool_message = await self.run_tool_call(
            assistant_msg.tool_calls[0], node_ids=node_ids
        )

        plan_result = TaskPlan.model_validate(tool_message.content)
        self.finalize_result(plan_result)

        await self.send_mermaid(plan_result, node_ids)

    def finalize_result(self, plan_result: TaskPlan) -> None:
        self.output.task_plan = plan_result
        self.output.summary = plan_result.to_summary()
        super().finalize_result(ok=1 <= len(plan_result.execution_order) <= MAX_TASKS)

    def modify_schema(self, tool_model: type, valid_ids: list[str]):
        if not valid_ids:
            raise ValueError("No valid ids provided")

        if len(valid_ids) > MAX_TASKS:
            logger.warning(
                f"⚠️ TaskPlanWorkflow has too many valid ids removing {len(valid_ids) - MAX_TASKS} ids"
            )
            self.result.details["removed_ids"] = valid_ids[MAX_TASKS:]
            valid_ids = valid_ids[:MAX_TASKS]

        from openai import pydantic_function_tool

        tool = pydantic_function_tool(
            tool_model,
            name=tool_model.__name__,
            # description=f"Fill the schema for {tool_model.__name__}",
        )

        # Modify the schema
        schema = tool["function"]["parameters"]["$defs"]["Task"]

        # Fix the id field to have proper enum
        schema["properties"]["id"] = {
            "type": "string",
            "enum": valid_ids,
            "description": f"Task ID must be one of: {', '.join(valid_ids)}",
        }

        # Fix the depends_on field to have proper enum
        schema["properties"]["depends_on"] = {
            "type": "array",
            "items": {"type": "string", "enum": valid_ids},
            "description": f"Available dependency IDs: {', '.join(valid_ids)}",
        }

        return tool

    async def send_mermaid(
        self, task_plan: TaskPlan, node_ids: dict[str, BaseRequest]
    ) -> None:
        if not self.result.ok:
            await self.sse_stream.send_error(self.planner_failure_message)
            return

        from app.common.mermaid import get_mermaid_diagram

        try:
            diagram = get_mermaid_diagram(task_plan, node_ids)
        except Exception as e:
            logger.warning(f"⚠️ Error generating Mermaid diagram: {e}")
            await self.sse_stream.send_error(self.planner_failure_message)
            return

        await self.sse_stream.send_chars("__My Plan for Your Request__")
        await self.sse_stream.send_mermaid(diagram)
        # from common.utils import save_file
        # save_file(diagram, file_name="task_plan-dev")
