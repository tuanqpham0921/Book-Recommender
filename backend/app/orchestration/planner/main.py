import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.common.sse_stream import SSEStream
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.orchestration.request_context import RequestContext
from app.orchestration.planner.parse_intent import (
    InitialParseWorkflow,
    InitialParseOutput,
    InitialParseResult,
)
from app.orchestration.planner.strategy_classification import (
    StrategyClassificationWorkflow,
    StrategyClassificationOutput,
    StrategyClassificationResult,
)
from app.orchestration.planner.task_planner import (
    TaskPlanWorkflow,
    TaskPlanOutput,
    TaskPlan,
)
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.domains.base_request import BaseRequest
from common.operation import OperationResult
from app.common.prompt_loader import format_prompt
import logging
ChildWorkflowT = TypeVar("ChildWorkflowT", bound=UserFacingBaseWorkflow)

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class OrchestrationOutput(UserFacingOutput):
    session_id: str | None = None
    parse_result: InitialParseResult | None = None
    strategy_result: StrategyClassificationResult | None = None
    task_plan: TaskPlan | None = None
    diagram: str | None = None
    
    def _sub_summary(self) -> dict[str, Any]:
        parse_summary = self.parse_result.to_summary() if self.parse_result else None
        strategy_summary = (
            self.strategy_result.to_summary() if self.strategy_result else None
        )
        task_plan_summary = self.task_plan.to_summary() if self.task_plan else None

        return {
            "session_id": self.session_id,
            "parse_result": parse_summary,
            "strategy_result": strategy_summary,
            "task_plan": task_plan_summary,
        }


class ConversationOrchestrator(UserFacingBaseWorkflow[OrchestrationOutput]):
    initial_parse_failure_message = (
        "I couldn't understand your request. Please try again."
    )
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    summary_prompt_path = (
        "orchestration/planner/prompts/conversation_orchestration_summary.txt"
    )

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=OrchestrationOutput,
        )
        self.user_message = user_message

    def _child_workflow(self, workflow_cls: type[ChildWorkflowT]) -> ChildWorkflowT:
        return workflow_cls(self.sse_stream, self.user_message, self.llm_client)

    def add_step(
        self, step: OperationResult[Any], *, raise_on_failure: bool = True
    ) -> OperationResult[Any]:
        step = super().add_step(step, raise_on_failure=raise_on_failure)
        output = step.output

        if isinstance(output, InitialParseOutput):
            self.output.parse_result = output.parse_result
        elif isinstance(output, StrategyClassificationOutput):
            self.output.strategy_result = output.strategy_result
        elif isinstance(output, TaskPlanOutput):
            self.output.task_plan = output.task_plan

        return step

    async def _run_phase(
        self,
        workflow_call: Callable[[], Awaitable[OperationResult[Any]]],
        *,
        error_message: str,
    ) -> OperationResult[Any] | None:
        result = await self.run_async_step(workflow_call(), raise_on_failure=False)
        if result is None:
            return None

        if not result.ok:
            if result.run_time_error:
                await self.sse_stream.send_error(error_message)

            self.result.ok = False
            self.result.message = error_message
            return None
        return result

    async def _run_initial_parse(self) -> OperationResult[Any] | None:
        workflow = self._child_workflow(InitialParseWorkflow)
        result = await self._run_phase(
            workflow,
            error_message=self.initial_parse_failure_message,
        )
        if result is None:
            return None

        await self.sse_stream.send_divider()
        return result

    async def _run_strategy_classification(
        self, system_goals: str
    ) -> OperationResult[Any] | None:
        workflow = self._child_workflow(StrategyClassificationWorkflow)
        return await self._run_phase(
            lambda: workflow(system_goals),
            error_message=self.strategy_classification_failure_message,
        )

    async def _run_task_planner(
        self, system_goals: str, node_ids: dict[str, BaseRequest]
    ) -> OperationResult[Any] | None:
        workflow = self._child_workflow(TaskPlanWorkflow)
        return await self._run_phase(
            lambda: workflow(system_goals, node_ids),
            error_message=self.task_planner_failure_message,
        )

    async def run(self, request_context: RequestContext) -> None:
        self.output.session_id = request_context.session_id
        self.output.chat_messages.append(self.user_message)

        parse_result = await self._run_initial_parse()
        if parse_result is None or not parse_result.ok:
            # TODO: Handle the case where the initial parse failed
            # with meaningful error message
            return
        
        system_goals = parse_result.output.parse_result.system_goals
        system_goals = "\n".join(["* " + goal.description + "\n" for goal in system_goals])

        strategy_result = await self._run_strategy_classification(system_goals)
        if strategy_result is None:
            return

        node_ids = self.output.strategy_result.get_accepted_node_ids()
        plan_result = await self._run_task_planner(system_goals, node_ids)
        if plan_result is None:
            return

        diagram = await self.send_mermaid(plan_result.output.task_plan, node_ids)
        self.output.diagram = diagram

        self.output.summary = await self.generate_summary()
        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
        await self.sse_stream.send_divider()

    async def generate_summary(self) -> dict[str, Any]:
        from common.utils import remove_json_empty_values

        sub_summary = remove_json_empty_values(self.output._sub_summary())
        prompt = format_prompt(
            self.summary_prompt_path,
            sub_summary=json.dumps(sub_summary, indent=2),
        )
        await self.generate_user_response([self.user_message], prompt=prompt)
        return sub_summary
    
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
        return diagram