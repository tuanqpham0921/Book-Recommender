import json
from typing import Any

from pydantic import Field

from app.common.sse_stream import SSEStream
from app.common.messages import APIMessage, AssistantMessage, UserMessage
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


# NOTE: this is okay for now
# we don't need parse_result, and strategy_result or diagram
# this should store conversation summary, failed tasks, internal summary message for llm
# maybe also referenced books or things from processing the steps
class PlannerOutput(AppWorkflowOutput):
    session_id: str | None = None
    parse_result: InitialParseOutput | None = None
    strategy_result: StrategyClassificationOutput | None = None
    diagram: str | None = None
    # full trace fed into this turn's LLM calls: chat_messages + everything
    # the workflows generated — persisted so chat_messages can be rebuilt
    pipeline_message: list[APIMessage] = Field(default_factory=list)
    # plain-string AssistantMessage contents produced this turn, in order —
    # joined with newlines at persist time (run_recorder) into the single
    # chat_runs.assistant_message TEXT column used to seed the next turn's
    # chat_messages
    assistant_message: list[str] = Field(default_factory=list)

    # TODO: implement this
    def to_summary(self) -> dict[str, Any]:
        return {}


def _assistant_texts(messages: list[APIMessage]) -> list[str]:
    return [
        m.content
        for m in messages
        if isinstance(m, AssistantMessage) and isinstance(m.content, str) and m.content
    ]


class PlannerWorkflow(AppBaseWorkflow[PlannerOutput]):
    initial_parse_failure_message = (
        "I couldn't understand your request. Please try again."
    )
    ui_loading_message = "Starting conversation..."
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    def __init__(
        self,
        sse_stream: SSEStream,
        user_message: UserMessage,
        llm_client: OpenAIClient,
        app_env: str | None = None,
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=PlannerOutput,
            app_env=app_env,
        )
        self.user_message = user_message

    async def run(self, request_context: RequestContext) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.output.session_id = request_context.session_id
        self.messages = request_context.pipeline_message
        self.messages.extend(request_context.chat_messages)
        self.messages.append(self.user_message)
        self.output.pipeline_message = self.messages

        parse_workflow = InitialParseWorkflow(
            self.sse_stream, self.user_message, self.llm_client, messages=self.messages
        )
        parse_result = await self.run_async_step(
            parse_workflow, raise_on_failure=False
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
            self.output.assistant_message = [self.initial_parse_failure_message]
            await self.sse_stream.send_chars(self.initial_parse_failure_message)
            return

        system_goals = parse_output.accepted_goals
        if not system_goals:
            # parse ok but nothing to plan — the parse workflow already
            # streamed the reply (small talk / out-of-scope / refusals)
            self.result.ok = True
            self.result.message = "Conversation handled without planning"
            self.output.assistant_message = _assistant_texts(self.messages)
            return

        strategy_workflow = StrategyClassificationWorkflow(
            self.sse_stream, self.user_message, self.llm_client, messages=self.messages
        )
        strategy_result = await self.run_async_step(
            strategy_workflow, system_goals, raise_on_failure=False
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
            self.output.assistant_message = [
                self.strategy_classification_failure_message
            ]
            await self.sse_stream.send_chars(
                self.strategy_classification_failure_message
            )
            return

        self.output.diagram = await self.send_mermaid(strategy_output)
        seen_description = set()
        await self.sse_stream.send_chars("\n\n## System Goals:\n")
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
        self.output.assistant_message = _assistant_texts(self.messages)

        # self.save_chat_messages()
        # self.save_conversation_result()

    async def send_mermaid(
        self, strategy_result: StrategyClassificationOutput
    ) -> str | None:
        from app.common.mermaid import get_mermaid_diagram

        diagram = None
        try:
            diagram = get_mermaid_diagram(
                strategy_result.execution_order,
                strategy_result.get_accepted_id_to_node(),
                strategy_result.get_execution_levels(),
            )
        except Exception as e:
            logger.warning(f"Error generating Mermaid diagram: {e}")
            return None

        if not diagram:
            logger.info("No Mermaid diagram generated (empty or invalid)")
            return None

        await self.sse_stream.send_chars("## My Plan for Your Request")
        await self.sse_stream.send_mermaid(diagram)
        return diagram
