import logging
from collections import defaultdict
from typing import Any, NamedTuple

from openai.types.chat import ParsedFunctionToolCall
from pydantic import Field

from clients.messages import UserMessage
from app.common.prompt_loader import format_prompt
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.node_input import NodeInput, ParsedInput
from app.registry import REGISTRY
from clients import OpenAIParserRequest

from app.domains.planjane.dial.mermaid import get_goals_mermaid_diagram
from .schemas import MAX_SYSTEM_GOALS, GoalParseRequest, SystemGoal

logger = logging.getLogger(__name__)

# The planner is reachable from both ends: the user's text, or the tool schema
# already filled in (see `GoalParseRequest.__call__`).
PlanJaneInput = NodeInput | ParsedInput[GoalParseRequest]

GOAL_GENERATOR_PROMPT_PATH = "domains/planjane/prompts/0_goal_generator.txt"
# PLAYGORUND_PROMPT_PATH = "../playground/prompting/planner_prompt._extended.txt"


class ExecutionOrder(NamedTuple):
    """The accepted goals arranged for execution.

    `layers` is a dependency layering: a goal depends only on earlier layers, so
    a layer is safe to run in any order or concurrently — which is the only
    reason to group. Running them flattened is therefore also correct.

    `unreachable` is every goal no layer could contain: in a cycle, or depending
    on one the planner refused. Returned rather than dropped — omitting them is
    how a user asks for three things, gets one, and is told it succeeded.
    """

    layers: list[list["SystemGoal"]]
    unreachable: list["SystemGoal"]


class PlanJaneOutput(NodeWorkflowOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    # Optional, not `list[str] = None`: model_dump_json emits `null` when
    # unset, and a non-optional annotation then rejects its own dump on reload.
    out_of_scope: list[str] | None = None

    # The rendered plan — plan presentation belongs to the plan.
    diagram: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "accepted_types": [goal.target_node_type for goal in self.accepted_goals],
            "num_rejected_system": len(self.refused_goals),
            "out_of_scope": self.out_of_scope,
        }

    def accepted_goals_ids(self) -> list[str]:
        return [goal.id for goal in self.accepted_goals]
    
    def id_to_node(self) -> dict[str, SystemGoal]:
        """The accepted goals keyed by the id other goals reference them by."""
        return {goal.id: goal for goal in self.accepted_goals}

    def execution_order(self) -> ExecutionOrder:
        """Layer the accepted goals by dependency depth (Kahn's algorithm).

        Each round emits every goal whose dependencies are all placed, then
        decrements the goals waiting on them. `ready` and `next_ready` are
        separate lists so the layer boundary holds by construction — snapshotting
        one queue's length while still pushing onto it is what let a goal share a
        layer with the dependency that unblocked it.

        A goal that never reaches zero is returned in `unreachable` rather than
        vanishing: a cycle, or a dependency the planner refused.
        """
        goals = self.id_to_node()

        # goal id -> the goals waiting on it, and how many each still waits
        # for. Both sides come off the same de-duplicated list, so a goal naming
        # a dependency twice is counted and decremented the same number of times.
        dependents: dict[str, list[str]] = defaultdict(list)
        blocked_by: dict[str, int] = {}
        for goal_id, goal in goals.items():
            deps = list(dict.fromkeys(goal.depends_on))
            # An unknown dependency id is counted but wired to nothing, so it
            # can never be decremented — which is what makes this goal come back
            # unreachable rather than run without its input.
            for dep_id in deps:
                if dep_id in goals:
                    dependents[dep_id].append(goal_id)
            blocked_by[goal_id] = len(deps)

        layers: list[list[SystemGoal]] = []
        ready = [goal_id for goal_id in goals if blocked_by[goal_id] == 0]
        while ready:
            layers.append([goals[goal_id] for goal_id in ready])

            next_ready: list[str] = []
            for goal_id in ready:
                for dependent_id in dependents[goal_id]:
                    blocked_by[dependent_id] -= 1
                    if blocked_by[dependent_id] == 0:
                        next_ready.append(dependent_id)
            ready = next_ready

        # by construction: anything no layer claimed could not be scheduled
        scheduled = {goal.id for layer in layers for goal in layer}
        unreachable = [
            goal for goal in goals.values() if goal.id not in scheduled
        ]
        if unreachable:
            logger.warning(
                "Goals that can never run (cycle, or depend on a refused "
                f"goal): {[goal.id for goal in unreachable]}"
            )

        return ExecutionOrder(layers=layers, unreachable=unreachable)

class PlanJaneExecutor(AppWorkflow[PlanJaneOutput]):
    ui_loading_message = "Thinking..."
    intent_reject_message = (
        "I can't help with that request. Please try again with a book-related question."
    )
    continuation_reject_message = "I don't have memory of earlier messages yet — please restate your full request in one message."

    tool_models: list[type] = [GoalParseRequest]

    async def run(self, node_input: PlanJaneInput) -> None:
        """Two ways in, one body.

        From natural language (`NodeInput`) the planner makes the tool call
        itself; handed an already-filled `GoalParseRequest` it skips to the
        processing. Everything after the branch is shared, which is the point —
        the tool schema can be exposed and called directly without a second
        implementation of what happens to the goals.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        if isinstance(node_input, NodeInput):
            parse_result = await self._run_llm_args_parse(node_input.query)
            self.process_parse_result(parse_result)
        else:
            # already validated as GoalParseRequest by the field's annotation
            self.process_parse_result(node_input.parsed_result)

        await self.finalize_result()

        # generate unable to help with
        if self.result.accepted_goals:
            await self.send_mermaid(self.result.accepted_goals)

    async def _run_llm_args_parse(self, query: str) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=GOAL_GENERATOR_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=REGISTRY.format_catalog(),
        )

        # NOTE: toggle on for prompting experiments
        # system_prompt = load_prompt(prompt_path=PLAYGORUND_PROMPT_PATH)

        # NOTE: the planner sees the whole catalog, so accuracy matters more
        # than cost here; cache hit rate is high and output is short
        req = OpenAIParserRequest(
            prompt=system_prompt,
            model="gpt-5.6-terra",
            reasoning_effort="none",
            # NOTE: this should be a list of previous messages as well
            # but for now we can just do clear and direct instructions
            #
            # `query`, not `self.user_message` — identical on the wire, but it
            # means a rewritten or clarified query is what gets parsed.
            messages=[UserMessage(content=query)],
            tool_models=[GoalParseRequest],
            max_completion_tokens=1000,
        )
        tool_call = await self.run_llm_args_parse(req)
        return tool_call

    async def finalize_result(self) -> None:
        # ok = a plan came out of this turn. Continuation is still decided
        # from accepted_goals, not from ok.
        super().finalize_result(ok=bool(self.result.accepted_goals))

    def process_parse_result(
        self, parse_result: GoalParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if len(parse_result.system_goals) == 0 and not parse_result.out_of_scope:
            msg = "Nothing was classified in the initial parse"
            self.record.ok = False
            logger.warning(msg)
            self.record.add_details(msg)
            raise RuntimeError(msg)

        self.result.out_of_scope = parse_result.out_of_scope

        # overflow goals are valid, just over the limit — same checks, so they
        # can fill capacity freed by refusals or wait in buffer_goals
        all_goals = parse_result.system_goals
        for goal in all_goals:
            reasons = []
            if goal.confidence < confident_tuning:
                reasons.append(f"Rejected: confidence too low ({goal.confidence})")
            if goal.target_node_type not in REGISTRY:
                reasons.append(
                    f"Rejected: target node type not supported ({goal.target_node_type})"
                )
            if reasons or goal._refusal:
                goal.refuse(*reasons)
                self.result.refused_goals.append(goal)
            elif len(self.result.accepted_goals) < MAX_SYSTEM_GOALS:
                self.result.accepted_goals.append(goal)
            else:
                self.result.buffer_goals.append(goal)

    async def send_mermaid(self, system_goals: list) -> str | None:
        """Render the accepted goals as a Mermaid flowchart and stream it.

        Returns the diagram, or None when there is nothing to draw or generation
        failed — never raises into the request. Lives here because the diagram
        *is* the plan rendered.
        """
        diagram = None
        diagram = get_goals_mermaid_diagram(system_goals)
        

        if not diagram:
            msg = "No Mermaid diagram generated (empty or invalid)"
            logger.warning(msg)
            self.add_details(msg)
            return None

        await self.sse_stream.send_chars("\n\n## My Plan for Your Request\n")
        await self.sse_stream.send_mermaid(diagram)
        self.result.diagram = diagram
        return diagram