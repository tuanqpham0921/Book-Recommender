from typing import Any

from pydantic import Field

from app.domains.planner.parse_intent import (
    PlanJaneExecutor,
    PlanJaneOutput,
)

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from common.utils.json_handler import load_json
from config import FilesLocationConstants

from .generation_node import GenerationNode, create_generation_nodes

import logging

logger = logging.getLogger(__name__)

# NOTE:
# this should be renamed to executor.py
# reserve main.py for endpoint if you want it to be a different service

# TODO:
# format this repo similar to books domains
# cleaner and each can have a executor format and prompt thing

# NOTE:
# this repo is a pre-flight or initial parse
# this should be executor.py that do things like
#   * check the cache, small talks, decide to call the planner or not
#   * clarification stuff
# the planner it's own workflow thing, that will return a plan to the this
# and the actual planner (planJane) should be outside of of app/domain
# I think(?)

# TODO: remove for prod
CACHE_DIR = FilesLocationConstants.PROJECT_ROOT / "playground" / "files" / "cache"
cache_mapping = {
    "Show me books similar to Pride and Prejudice": "Show me books similar to Pride and Prejudice",
    "Find books like 1984 or Brave New World": "Find books like 1984 or Brave New World",
    "Find books like 1984 or Brave New World, Dune, Brave New World": "Find books like 1984 or Brave New World, Dune, Brave New World",
}


def load_cached_parse_output(user_text: str) -> PlanJaneOutput | None:
    """Replay a recorded parse instead of calling the LLM, for the messages
    listed in cache_mapping. Returns None when there is no usable cache entry,
    so the caller falls through to the real parse workflow.

    The files are whole PlannerWorkflow OperationResult dumps, so the parse
    payload sits at output.parse_result."""
    file_name = cache_mapping.get(user_text)
    if not file_name:
        return None

    data = load_json(file_name, path=CACHE_DIR)
    if not isinstance(data, dict):
        return None

    payload = (data.get("output") or {}).get("parse_result")
    if not payload:
        logger.warning(f"Cache entry {file_name} has no output.parse_result")
        return None

    # save_file() writes these with remove_empty=True, which drops empty
    # lists — so a goal that depends on nothing comes back missing its
    # required depends_on. Put it back before validating.
    for key in ("accepted_goals", "refused_goals", "buffer_goals"):
        for goal in payload.get(key) or []:
            goal.setdefault("depends_on", [])

    try:
        return PlanJaneOutput.model_validate(payload)
    except Exception as e:
        logger.warning(f"Could not replay cached parse {file_name}: {e}")
        return None


# NOTE: this is okay for now
# we don't need parse_result, and strategy_result or diagram
# this should store conversation summary, failed tasks, internal summary message for llm
# maybe also referenced books or things from processing the steps
class PlannerOutput(NodeWorkflowOutput):
    session_id: str | None = None
    parse_result: PlanJaneOutput | None = None
    diagram: str | None = None

    # The terminal answer stage, appended by the planner rather than chosen by
    # the LLM — one per sink in the goal graph. See generation_node.py.
    generation_nodes: list[GenerationNode] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        # NOTE: we'll have more later
        # parse_result is None when the turn errored before parsing finished —
        # the summary still has to render for that run, it's the one you read
        return {"plan": self.parse_result.to_summary() if self.parse_result else None}

    def execution_order(self):
        return self.parse_result.execution_order()

    def accepted_goals_ids(self) -> list[str]:
        return self.parse_result.accepted_goals_ids()


class PlannerWorkflow(AppWorkflow[PlannerOutput]):
    initial_parse_failure_message = (
        "I couldn't understand your request. Please try again."
    )
    ui_loading_message = "Starting conversation..."
    strategy_classification_failure_message = "I can't find any relevant strategies for your request. Please try again with more specific keywords."
    task_planner_failure_message = "I tried to create a plan, but it was too large or invalid. Try narrowing your request."

    async def run(self, query: str, artifacts: dict[str, Any]) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.result.session_id = self.session_id
        self.messages.append(self.user_message)

        parse_output = load_cached_parse_output(query)
        if parse_output is None:
            parse_workflow = PlanJaneExecutor(self.ctx, messages=self.messages)
            parse_result = await self.run_async_step(
                parse_workflow(query=query, artifacts=artifacts),
                raise_on_failure=False,
            )

            # narrow through a local: the workflow pre-initializes its output,
            # so it is never None; parse_workflow.result raises if it ever were
            parse_output = parse_workflow.result
            self.result.parse_result = parse_output

            if not parse_result.ok:
                self.record.ok = False
                if parse_result.runtime_error:
                    self.record.runtime_error = parse_result.runtime_error
                    await self.sse_stream.send_error(self.initial_parse_failure_message)
                    return
                # await self.sse_stream.send_chars(self.initial_parse_failure_message)
                return
        else:
            logger.info(f"Replaying cached parse for: {query}")
            self.result.parse_result = parse_output

        system_goals = parse_output.accepted_goals
        if not system_goals:
            # parse ok but nothing to plan — the parse workflow already
            # streamed the reply (small talk / out-of-scope / refusals)
            self.record.ok = True
            return

        # Attach the answer stage before anything is drawn, so both diagrams
        # show the plan the user actually gets — ending in an answer, not in a
        # retrieval. Depends only on goal ids, so it needs no parsed arguments.
        generation_nodes = create_generation_nodes(system_goals)
        self.result.generation_nodes = generation_nodes

        await self.send_mermaid(system_goals, generation_nodes)
        # ------------------------------------------------------------------------------------------------

        # parsed_system_goals = await self.parse_goals_arguments(system_goals)
        # self.result.parsed_results = parsed_system_goals
        # await self.send_mermaid_parsed(parsed_system_goals, generation_nodes)

        self.record.ok = True

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
        self.result.diagram = diagram
        return diagram
