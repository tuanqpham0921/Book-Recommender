import json
from typing import Any

from app.common.sse_stream import SSEStream
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.orchestration.request_context import RequestContext
from app.domains.planner.parse_intent import (
    InitialParseWorkflow,
    InitialParseOutput,
)
from app.domains.planner.strategy_classification import (
    StrategyClassificationWorkflow,
    StrategyClassificationOutput,
)

from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from common.operation import OperationResult
from app.common.prompt_loader import format_prompt
import logging

logger = logging.getLogger(__name__)

CONVERSATION_SUMMARY_PROMPT_PATH = (
    "domains/planner/prompts/3_conversation_orchestration_summary.txt"
)


class OrchestrationOutput(AppWorkflowOutput):
    session_id: str | None = None
    parse_result: InitialParseOutput | None = None
    strategy_result: StrategyClassificationOutput | None = None
    diagram: str | None = None

    # TODO: implement this
    def to_summary(self) -> dict[str, Any]:
        return {}


class ConversationOrchestrator(AppBaseWorkflow[OrchestrationOutput]):
    initial_parse_failure_message = (
        "I couldn't understand your request. Please try again."
    )
    ui_loading_message = "Starting conversation..."
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=OrchestrationOutput,
        )
        self.user_message = user_message

    async def run(self, request_context: RequestContext) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.output.session_id = request_context.session_id
        self.messages.append(self.user_message)

        parse_workflow = InitialParseWorkflow(
            self.sse_stream, self.user_message, self.llm_client, messages=self.messages
        )
        parse_result = await self.run_async_step(
            parse_workflow(), raise_on_failure=False
        )
        # narrow through a local: the workflow pre-initializes its output,
        # so it is never None; parse_workflow.output raises if it ever were
        parse_output = parse_workflow.output
        self.output.parse_result = parse_output

        if not parse_result.ok:
            self.result.ok = False
            self.result.message = self.initial_parse_failure_message
            if parse_result.runtime_error:
                await self.sse_stream.send_error(self.initial_parse_failure_message)
                return
            await self.sse_stream.send_chars(self.initial_parse_failure_message)
            return

        # return
        # ------------------------------------------------------------------------------------------------

        system_goals = parse_output.accepted_goals
        if not system_goals:
            # parse ok but nothing to plan — the parse workflow already
            # streamed the reply (small talk / out-of-scope / refusals)
            self.result.ok = True
            self.result.message = "Conversation handled without planning"
            self.save_chat_messages()
            self.save_conversation_result()
            return

        strategy_workflow = StrategyClassificationWorkflow(
            self.sse_stream, self.user_message, self.llm_client, messages=self.messages
        )
        strategy_result = await self.run_async_step(
            strategy_workflow(system_goals), raise_on_failure=False
        )
        strategy_output = strategy_workflow.output
        self.output.strategy_result = strategy_output
        if not strategy_result.ok:
            self.result.ok = False
            self.result.message = self.strategy_classification_failure_message
            if strategy_result.runtime_error:
                await self.sse_stream.send_error(
                    self.strategy_classification_failure_message
                )
                return
            await self.sse_stream.send_chars(
                self.strategy_classification_failure_message
            )
            return

        self.output.diagram = await self.send_mermaid(strategy_output)
        seen_description = set()
        await self.sse_stream.send_chars("\n\n# System Goals:\n")
        for system_goal in parse_output.accepted_goals:
            if system_goal.description in seen_description:
                continue
            await self.sse_stream.send_chars(f"- {system_goal.description}\n")
            seen_description.add(system_goal.description)

        await self.sse_stream.send_divider()
        # ------------------------------------------------------------------------------------------------
        # Final response

        # await self.generate_summary()
        # ------------------------------------------------------------------------------------------------

        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"

        self.save_chat_messages()
        self.save_conversation_result()

    async def send_mermaid(
        self, strategy_result: StrategyClassificationOutput
    ) -> str | None:
        from app.common.mermaid import get_mermaid_diagram

        try:
            diagram = get_mermaid_diagram(
                strategy_result.execution_order,
                strategy_result.get_accepted_id_to_node(),
            )
        except Exception as e:
            logger.warning(f"Error generating Mermaid diagram: {e}")
            return None

        await self.sse_stream.send_chars("# My Plan for Your Request")
        await self.sse_stream.send_mermaid(diagram)
        return diagram

    def save_conversation_result(self, name: str = "dev") -> None:
        from common.utils import save_file

        data = self.result.model_dump()
        data.pop("steps", None)
        save_file(data, file_name=f"conversation_result_{name}.json")

    def save_chat_messages(self, name: str = "dev") -> None:
        from common.utils import save_file
        from common.utils import to_serializable

        if not self.messages:
            return
        logger.info(f"Saving chat messages to {name}.json")
        data = {
            "chat_messages": to_serializable(self.messages),
            "token_usage": to_serializable(self.result.token_usage),
        }
        save_file(data, file_name=f"chat_messages_{name}.json")
