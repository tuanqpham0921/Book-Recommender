from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.common.sse_stream import SSEStream
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.orchestration.request_context import RequestContext
from app.orchestration.planner.parse_intent import (
    InitialParseWorkflow,
    InitialParseResult,
)
from app.orchestration.planner.strategy_classification import (
    StrategyClassificationWorkflow,
    StrategyClassificationResult,
)
from app.orchestration.planner.task_planner import TaskPlanWorkflow, TaskPlan
from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from common.operation import OperationResult


@dataclass(slots=True)
class OrchestrationOutput(UserFacingOutput):
    session_id: str | None = None
    parse_result: InitialParseResult | None = None
    strategy_result: StrategyClassificationResult | None = None
    task_plan: TaskPlan | None = None


class ConversationOrchestrator(UserFacingBaseWorkflow[OrchestrationOutput]):
    initial_parse_failure_message = "I couldn't understand your request. Please try again."
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=OrchestrationOutput,
        )
        self.user_message = user_message

    async def _run_phase(
        self,
        workflow_call: Callable[[], Awaitable[OperationResult[Any]]],
        *,
        error_message: str,
    ) -> OperationResult[Any] | None:
        result = await self.run_async_step(workflow_call(), raise_on_failure=False)
        if not result.ok:
            await self.sse_stream.send_error(error_message)
            self.result.ok = False
            self.result.message = error_message
            return None
        return result

    async def _run_initial_parse(self) -> OperationResult[Any] | None:
        workflow = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        result = await self._run_phase(
            workflow,
            error_message=self.initial_parse_failure_message,
        )
        if result is None:
            return None

        self.output.parse_result = result.output.parse_result
        await self.sse_stream.send_divider()
        return result

    async def _run_strategy_classification(
        self, in_domain_message: str
    ) -> OperationResult[Any] | None:
        workflow = StrategyClassificationWorkflow(
            self.sse_stream, self.user_message, self.llm_client
        )
        result = await self._run_phase(
            lambda: workflow(in_domain_message),
            error_message=self.strategy_classification_failure_message,
        )
        if result is None:
            return None

        self.output.strategy_result = result.output.strategy_result
        node_ids = result.output.strategy_result.get_accepted_node_ids()
        if not node_ids:
            await self.sse_stream.send_error(self.strategy_classification_failure_message)
            self.result.ok = False
            self.result.message = self.strategy_classification_failure_message
            return None

        return result

    async def _run_task_planner(
        self, in_domain_message: str, node_ids: dict
    ) -> OperationResult[Any] | None:
        workflow = TaskPlanWorkflow(self.sse_stream, self.user_message, self.llm_client)
        return await self._run_phase(
            lambda: workflow(in_domain_message, node_ids),
            error_message=self.task_planner_failure_message,
        )

    async def run(self, request_context: RequestContext) -> None:
        self.output.session_id = request_context.session_id
        self.output.chat_messages.append(self.user_message)

        parse_result = await self._run_initial_parse()
        if parse_result is None:
            return

        in_domain_message = self.output.parse_result.model_dump_json(
            include={"user_query_domain", "continue_pipeline", "reasoning"}
        )
        request_context.in_domain_message = in_domain_message

        strategy_result = await self._run_strategy_classification(in_domain_message)
        if strategy_result is None:
            return

        node_ids = self.output.strategy_result.get_accepted_node_ids()
        plan_result = await self._run_task_planner(in_domain_message, node_ids)
        if plan_result is None:
            return

        self.output.task_plan = plan_result.output.task_plan
        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
        await self.sse_stream.send_divider()
