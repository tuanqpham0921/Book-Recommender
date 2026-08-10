"""Triage — what happens to a turn before, and instead of, planning.

Sits between `Orchestrator` (transport: SSE lifecycle, timeouts, cancellation,
recording) and `PlanJane` (produce a plan). Its job is to decide **whether to
plan at all**: replay a cached plan, answer small talk, refuse out-of-scope, or
hand the turn to the planner.

It lives here rather than in `app/domains/` because it is not a capability —
no `NodeSpec.executor` will ever point at it, and its only domain
knowledge is which planner to call. It is a separate `AppWorkflow` rather than
methods on `Orchestrator` because `Orchestrator` owns no envelope: folding the
decisions in would mean a cache hit or a refusal produced no step in the trace
tree, and `chat_runs.planner` would lose its shape.
"""

import logging
from typing import Any

from app.common.request_context import RequestContext  # noqa: F401  (re-export shape)
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.planjane import PlanJaneExecutor, PlanJaneOutput
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
    """Replay a recorded plan instead of calling the LLM, for the messages
    listed in cache_mapping. Returns None when there is no usable cache entry,
    so the caller falls through to the real planner.

    The files are whole triage OperationResult dumps, so the plan payload sits
    at output.parse_result."""
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
        logger.warning(f"Could not replay cached plan {file_name}: {e}")
        return None


# NOTE: this is okay for now
# this should store conversation summary, failed tasks, internal summary message
# for llm — maybe also referenced books or things from processing the steps
class TriageOutput(NodeWorkflowOutput):
    session_id: str | None = None

    # The plan, when triage decided to produce one. None means the turn was
    # handled without planning (or failed before the planner returned).
    #
    # Field name kept as `parse_result` on purpose: it is a *serialized* path.
    # evals/report_system_goals.py reads accepted goals at
    # planner.response.result.parse_result, the checked-in cache files key on
    # it, and every recorded chat_runs row carries it. Renaming it to `plan`
    # means changing all four in lockstep — worth doing, not worth doing
    # silently as part of a file move.
    parse_result: PlanJaneOutput | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"plan": self.parse_result.to_summary() if self.parse_result else None}

    @property
    def diagram(self) -> str | None:
        """The plan's Mermaid diagram. Rendered by PlanJane, which owns plan
        presentation; surfaced here because `chat_runs.mermaid` is promoted out
        of this envelope (run_recorder.py) and the review page reads it."""
        return self.parse_result.diagram if self.parse_result else None

    def execution_order(self):
        return self.parse_result.execution_order()

    def accepted_goals_ids(self) -> list[str]:
        return self.parse_result.accepted_goals_ids()


class TriageWorkflow(AppWorkflow[TriageOutput]):
    planner_failure_message = "I couldn't understand your request. Please try again."
    ui_loading_message = "Starting conversation..."

    @property
    def artifact(self) -> dict[str, Any]:
        """What triage hands downstream is the **plan**, not its own envelope.

        The task runner executes a plan; it should not have to know a triage
        layer exists — and if it required `TriageOutput` it would have to import
        upward out of `app/domains/` into this package. Empty when the turn was
        handled without planning, which `require_artifact` then rejects.
        """
        plan = self.result.parse_result
        return {plan.id or type(plan).__name__: plan} if plan else {}

    async def run(self, query: str, artifacts: dict[str, Any]) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.result.session_id = self.session_id
        self.messages.append(self.user_message)

        cached = load_cached_parse_output(query)
        if cached is not None:
            logger.info(f"Replaying cached plan for: {query}")
            self.result.parse_result = cached
            self.record.ok = True
            return

        planner = PlanJaneExecutor(self.ctx, messages=self.messages)
        planner_record = await self.run_async_step(
            planner(query=query, artifacts=artifacts),
            raise_on_failure=False,
        )

        # narrow through a local: the workflow pre-initializes its output, so it
        # is never None; planner.result raises if it ever were
        self.result.parse_result = planner.result

        if not planner_record.ok:
            self.record.ok = False
            if planner_record.runtime_error:
                self.record.runtime_error = planner_record.runtime_error
                await self.sse_stream.send_error(self.planner_failure_message)
            return

        # ok with no goals is a handled turn, not a failure — PlanJane already
        # streamed the reply (small talk / out-of-scope / refusals)
        self.record.ok = True
