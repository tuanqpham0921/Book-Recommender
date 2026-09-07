"""Triage — what happens to a turn before, and instead of, planning.

Sits between `Orchestrator` (transport) and `PlanJane` (produce a plan), and
decides whether to plan at all: replay a cached plan, answer small talk, refuse
out-of-scope, or hand the turn to the planner.

Not in `app/domains/` because it is not a capability — no `NodeSpec.executor`
will point at it. A workflow rather than methods on `Orchestrator` because
`Orchestrator` owns no envelope, so a cache hit or a refusal would produce no
step in the trace tree.
"""

import logging
from typing import Any

from app.common.request_context import RequestContext  # noqa: F401  (re-export shape)
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.node_input import NodeInput
from app.domains.planjane import ExecutionOrder, PlanJaneExecutor, PlanJaneOutput
from common.utils.json_handler import load_json
from config import FilesLocationConstants

logger = logging.getLogger(__name__)

# TODO: remove for prod
CACHE_DIR = FilesLocationConstants.PROJECT_ROOT / "playground" / "files" / "cache"
cache_mapping = {
    "Show me books similar to Pride and Prejudice": "Show me books similar to Pride and Prejudice",
    "Find books like 1984 or Brave New World": "Find books like 1984 or Brave New World",
    "Find books like 1984 or Brave New World, Dune, Brave New World": "Find books like 1984 or Brave New World, Dune, Brave New World",
}


def load_cached_parse_output(user_text: str) -> PlanJaneOutput | None:
    """Replay a recorded plan instead of calling the LLM, for the messages in
    cache_mapping. None when there is no usable entry, so the caller falls
    through to the real planner. The files are whole triage record dumps."""
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

    # save_file() writes with remove_empty=True, dropping empty lists, so a
    # goal depending on nothing comes back missing its required depends_on
    for key in ("accepted_goals", "refused_goals", "buffer_goals"):
        for goal in payload.get(key) or []:
            goal.setdefault("depends_on", [])

    try:
        return PlanJaneOutput.model_validate(payload)
    except Exception as e:
        logger.warning(f"Could not replay cached plan {file_name}: {e}")
        return None


# NOTE: this is okay for now
# this should store conversation summary, failed tasks, internal summary message
# for llm — maybe also referenced books or things from processing the steps
class TriageOutput(NodeWorkflowOutput):
    session_id: str | None = None

    # The plan, when triage produced one. None means the turn was handled
    # without planning, or failed before the planner returned.
    #
    # The name is a *serialized* path: evals/report_system_goals.py, the cache
    # files and every chat_runs row all key on `parse_result`. Renaming it to
    # `plan` means changing all four in lockstep.
    parse_result: PlanJaneOutput | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"plan": self.parse_result.to_summary() if self.parse_result else None}

    @property
    def diagram(self) -> str | None:
        """The plan's Mermaid diagram, rendered by PlanJane. Surfaced here
        because `chat_runs.mermaid` is promoted out of this envelope and the
        review page reads it."""
        return self.parse_result.diagram if self.parse_result else None

    def execution_order(self) -> ExecutionOrder | None:
        if not self.parse_result:
            return None
        return self.parse_result.execution_order()

    def accepted_goals_ids(self) -> list[str] | None:
        if not self.parse_result:
            return None
        return self.parse_result.accepted_goals_ids()


class TriageWorkflow(AppWorkflow[TriageOutput]):
    planner_failure_message = "I couldn't understand your request. Please try again."
    ui_loading_message = "Starting conversation..."

    async def run(self, node_input: NodeInput, *, use_caching=True) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        query = node_input.instruction
        self.result.session_id = self.session_id

        # 1. replay a recorded plan when one exists — no LLM, same output shape
        if use_caching:
            cached = load_cached_parse_output(query)
            if cached is not None:
                logger.info(f"Replaying cached plan for: {query}")
                self.result.parse_result = cached
                self.finalize_result(ok=True)
                return

        # 2. plan. A bare await, not `unwrap()`: triage decides what a failed
        # planner means (a specific message to the user), so it wants the
        # envelope
        planner = PlanJaneExecutor(self.ctx, messages=self.messages)
        planner_record = await planner(NodeInput(instruction=query))

        # the workflow pre-initializes its output, so this is never None
        self.result.parse_result = planner.result

        # 3. triage owns what a planner failure means to the user
        if not planner_record.ok:
            if planner_record.runtime_error:
                self.record.runtime_error = planner_record.runtime_error
                await self.sse_stream.send_error(self.planner_failure_message)
            self.finalize_result(ok=False)
            return

        # ok with no goals is a handled turn, not a failure — PlanJane already
        # streamed the reply (small talk / out-of-scope / refusals)
        self.finalize_result(ok=True)
