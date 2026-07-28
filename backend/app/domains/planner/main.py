import json
from typing import Any, cast

from pydantic import Field

from app.common.sse_stream import SSEStream
from app.common.messages import APIMessage, AssistantMessage, UserMessage
from clients.openai_client import OpenAIClient
from app.orchestration.request_context import RequestContext
from app.domains.planner.parse_intent import (
    InitialParseWorkflow,
    InitialParseOutput,
)

from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from common.operation import OperationResult
from app.common.prompt_loader import format_prompt
from app.domains.base_request import BaseRequest

from .args_parser import build_arg_parser_request, extract_parsed_request
from .generation_node import GenerationNode, create_generation_nodes

import logging

logger = logging.getLogger(__name__)


# NOTE: this is okay for now
# we don't need parse_result, and strategy_result or diagram
# this should store conversation summary, failed tasks, internal summary message for llm
# maybe also referenced books or things from processing the steps
class PlannerOutput(AppWorkflowOutput):
    session_id: str | None = None
    parse_result: InitialParseOutput | None = None
    diagram: str | None = None
    
    parsed_results: list[BaseRequest] | None = None
    parsed_diagram: str | None = None

    # The terminal answer stage, appended by the planner rather than chosen by
    # the LLM — one per sink in the goal graph. See generation_node.py.
    generation_nodes: list[GenerationNode] = Field(default_factory=list)

    # TODO: implement this
    def to_summary(self) -> dict[str, Any]:
        return {}


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
                self.result.runtime_error = parse_result.runtime_error
                await self.sse_stream.send_error(self.initial_parse_failure_message)
                return
            # await self.sse_stream.send_chars(self.initial_parse_failure_message)
            return

        system_goals = parse_output.accepted_goals
        if not system_goals:
            # parse ok but nothing to plan — the parse workflow already
            # streamed the reply (small talk / out-of-scope / refusals)
            self.result.ok = True
            self.result.message = "Conversation handled without planning"
            return

        # Attach the answer stage before anything is drawn, so both diagrams
        # show the plan the user actually gets — ending in an answer, not in a
        # retrieval. Depends only on goal ids, so it needs no parsed arguments.
        generation_nodes = create_generation_nodes(system_goals)
        self.output.generation_nodes = generation_nodes

        await self.send_mermaid(system_goals, generation_nodes)
        # ------------------------------------------------------------------------------------------------

        parsed_system_goals = await self.parse_goals_arguments(system_goals)
        self.result.output.parsed_results = parsed_system_goals
        await self.send_mermaid_parsed(parsed_system_goals, generation_nodes)

        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
    
    async def parse_goals_arguments(self, system_goals: list) -> list[BaseRequest]:
        """Testing the arugment parser. Should be in task_runner later(?)

        One LLM call per goal, each run as its own step so the call lands in
        self.result.steps and its tokens roll up into the workflow's
        token_usage. A failed call aborts the workflow via StepFailure — the
        same outcome as before, but reported with the client's error message
        instead of an AttributeError on a None output.
        """
        parsed_system_goals = []
        for goal in system_goals:
            await self.sse_stream.send_ui_loading(f"parsing argument for goal: {goal.id}")
            
            step_result = await self.run_async_step(
                self.llm_client.execute(
                    build_arg_parser_request(goal)
                )
            )
            assistant_msg = cast(AssistantMessage, step_result.output)
            parsed_system_goals.append(extract_parsed_request(goal, assistant_msg))

            await self.sse_stream.send_chars(f"- loaded argument for goal: {goal.id}\n")

        return parsed_system_goals
    
    async def send_mermaid_parsed(
        self,
        parsed_system_goals: list[BaseRequest],
        generation_nodes: list[GenerationNode] | None = None,
    ) -> str | None:
        """Render the parsed task requests as a Mermaid flowchart and stream it
        to the client. Same contract as send_mermaid — returns the diagram, or
        None when there is nothing to draw or generation failed.

        The graph has the same shape as the goal diagram: each request carries
        its goal's id and depends_on, so only the box contents differ (typed
        arguments instead of the goal description).
        """
        from app.common.mermaid import get_parsed_mermaid_diagram

        diagram = None
        try:
            diagram = get_parsed_mermaid_diagram(parsed_system_goals, generation_nodes)
        except Exception as e:
            logger.warning(f"Error generating parsed Mermaid diagram: {e}")
            return None

        if not diagram:
            logger.info("No parsed Mermaid diagram generated (empty or invalid)")
            return None

        await self.sse_stream.send_chars("\n\n## Task Details\n")
        await self.sse_stream.send_mermaid(diagram)
        self.output.parsed_diagram = diagram
        return diagram


    async def send_mermaid(
        self, system_goals: list, generation_nodes: list[GenerationNode] | None = None
    ) -> str | None:
        """Render the accepted system goals as a Mermaid flowchart and stream
        it to the client. Returns the diagram string, or None when there is
        nothing to draw or generation failed (never raises into the request)."""
        from app.common.mermaid import get_goals_mermaid_diagram

        diagram = None
        try:
            diagram = get_goals_mermaid_diagram(system_goals, generation_nodes)
        except Exception as e:
            logger.warning(f"Error generating Mermaid diagram: {e}")
            return None

        if not diagram:
            logger.info("No Mermaid diagram generated (empty or invalid)")
            return None

        await self.sse_stream.send_chars("\n\n## My Plan for Your Request\n")
        await self.sse_stream.send_mermaid(diagram)
        self.output.diagram = diagram
        return diagram
