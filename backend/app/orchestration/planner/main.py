from dataclasses import dataclass

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
from app.common.workflow import UserFacingBaseWorkflow, UserFacingWorkflowResult


@dataclass(slots=True)
class OrchestrationResult(UserFacingWorkflowResult[None]):
    session_id: str | None = None
    parse_result: InitialParseResult | None = None
    strategy_result: StrategyClassificationResult | None = None
    task_plan: TaskPlan | None = None


class ConversationOrchestrator(UserFacingBaseWorkflow[None]):
    result_class = OrchestrationResult

    initial_parse_failure_message = "I couldn't understand your request. Please try again."
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=None,
        )
        self.user_message = user_message

    async def run(self, request_context: RequestContext) -> None:
        self.result.session_id = request_context.session_id
        self.result.chat_messages.append(self.user_message)

        initial_parse = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        initial_parse_result = await self.run_async_step(
            initial_parse(),
            raise_on_failure=False,
        )
        if not initial_parse_result.ok:
            await self.sse_stream.send_error(self.initial_parse_failure_message)
            return

        self.result.parse_result = initial_parse_result.output
        await self.sse_stream.send_divider()

        in_domain_message = initial_parse_result.output.model_dump_json(
            include={"user_query_domain", "continue_pipeline", "reasoning"}
        )
        request_context.in_domain_message = in_domain_message

        strategy_classification = StrategyClassificationWorkflow(
            self.sse_stream, self.user_message, self.llm_client
        )
        strategy_classification_result = await self.run_async_step(
            strategy_classification(in_domain_message),
            raise_on_failure=False,
        )

        if not strategy_classification_result.ok:
            await self.sse_stream.send_error(self.strategy_classification_failure_message)
            return

        self.result.strategy_result = strategy_classification_result.output
        node_ids = strategy_classification_result.output.get_accepted_node_ids()
        if not node_ids:
            await self.sse_stream.send_error(self.strategy_classification_failure_message)
            return

        task_planner = TaskPlanWorkflow(self.sse_stream, self.user_message, self.llm_client)
        task_planner_result = await self.run_async_step(
            task_planner(in_domain_message, node_ids),
            raise_on_failure=False,
        )
        if not task_planner_result.ok:
            await self.sse_stream.send_error(self.task_planner_failure_message)
            return

        self.result.task_plan = task_planner_result.output
        await self.sse_stream.send_divider()

        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
