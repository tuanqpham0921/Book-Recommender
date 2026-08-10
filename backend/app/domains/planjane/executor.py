import logging
from typing import Any

from openai.types.chat import ParsedFunctionToolCall
from pydantic import Field

from app.common.messages import UserMessage
from app.common.prompt_loader import format_prompt
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.registry import REGISTRY
from clients import OpenAIParserRequest

from .mermaid import get_goals_mermaid_diagram
from .schemas import MAX_SYSTEM_GOALS, GoalParseRequest, SystemGoal

logger = logging.getLogger(__name__)

GOAL_GENERATOR_PROMPT_PATH = "domains/planjane/prompts/0_goal_generator.txt"
# PLAYGORUND_PROMPT_PATH = "../playground/prompting/planner_prompt._extended.txt"


# NOTE: there's a bug if
# task_1 -> task_2
# if task_1 is rejected then task_2 should not still depend on or run
# you need the previous pruning
class PlanJaneOutput(NodeWorkflowOutput):
    accepted_goals: list[SystemGoal] = Field(default_factory=list)
    refused_goals: list[SystemGoal] = Field(default_factory=list)
    buffer_goals: list[SystemGoal] = Field(default_factory=list)

    # Optional, not `list[str] = None`: model_dump_json emits `null` here when
    # unset, and a non-optional annotation then rejects its own dump on reload
    # — which is how chat_runs rows get replayed.
    out_of_scope: list[str] | None = None

    # The rendered plan. Lives on the plan, not on whatever called the planner:
    # drawing the plan is plan presentation.
    diagram: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "accepted_types": [goal.target_node_type for goal in self.accepted_goals],
            "num_rejected_system": len(self.refused_goals),
            "out_of_scope": self.out_of_scope,
        }

    def accepted_goals_ids(self) -> list[str]:
        return [goal.id for goal in self.accepted_goals]

    def to_llm_messages(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.out_of_scope:
            payload["out_of_scope"] = self.out_of_scope
        if self.refused_goals:
            payload["refused_goals"] = [
                (g.description, g.refusal_reasons) for g in self.refused_goals
            ]

        return payload

    # TODO:
    # this is wrong, you need the indegree
    def execution_order(self):
        from collections import defaultdict

        order = defaultdict(list)

        for node in self.accepted_goals:
            order[len(node.depends_on)].append(node)
        return order


class PlanJaneExecutor(AppWorkflow[PlanJaneOutput]):
    ui_loading_message = "Thinking..."
    intent_reject_message = (
        "I can't help with that request. Please try again with a book-related question."
    )
    continuation_reject_message = "I don't have memory of earlier messages yet — please restate your full request in one message."

    tool_models: list[type] = [GoalParseRequest]

    async def run(self, query: str, artifacts: dict[str, Any]) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        parse_result = await self._run_llm_args_parse(query)
        # parsed_arguments is typed `object | None` by the openai lib; the
        # parser validated it against GoalParseRequest, so the cast holds
        self.process_parse_result(parse_result)
        # NOTE: the output needs to be added somewhere correctly

        payload = self.result.to_llm_messages()
        await self.finalize_result(payload)

        # generate unable to help with
        if self.result.out_of_scope:
            await self.sse_stream.send_chars("\n\n I can't do:\n")
            for unsupported in self.result.out_of_scope:
                await self.sse_stream.send_chars(f"- {unsupported}\n")

        if self.result.accepted_goals:
            await self.send_mermaid(self.result.accepted_goals)

    async def send_mermaid(self, system_goals: list) -> str | None:
        """Render the accepted system goals as a Mermaid flowchart and stream
        it to the client. Returns the diagram string, or None when there is
        nothing to draw or generation failed (never raises into the request).

        Drawing the plan lives here rather than on the caller: the diagram *is*
        the plan rendered, so a caller that drew it would be doing the planner's
        job.
        """
        diagram = None
        try:
            diagram = get_goals_mermaid_diagram(system_goals)
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

    async def _run_llm_args_parse(self, query: str) -> ParsedFunctionToolCall:
        system_prompt = format_prompt(
            prompt_path=GOAL_GENERATOR_PROMPT_PATH,
            TOOLS_NAME_DESCRIPTION=REGISTRY.format_catalog(),
        )

        # NOTE: toggle on for prompting experiments
        # system_prompt = load_prompt(prompt_path=PLAYGORUND_PROMPT_PATH)

        # NOTE: using gpt4.1 because the system goals sees the whole catalog
        # it's very important that this part is done correctly
        # cache hit rate is high, and output generation is lower
        # we can optimize
        req = OpenAIParserRequest(
            prompt=system_prompt,
            model="gpt-5.6-terra",
            reasoning_effort="none",
            # NOTE: this should be a list of previous messages as well
            # but for now we can just do clear and direct instructions
            #
            # `query`, not `self.user_message` — identical on the wire
            # (to_openai_dict emits only role/content), but it means a query
            # the planner rewrote or clarified is what actually gets parsed.
            messages=[UserMessage(content=query)],
            tool_models=[GoalParseRequest],
            max_completion_tokens=1000,
        )
        tool_call = await self.run_llm_args_parse(req)
        return tool_call

    async def finalize_result(self, payload) -> None:
        # ok = the conversation was handled: either there are goals to plan,
        # or a substantive reply (out-of-scope / refusals) was
        # streamed to the user. The orchestrator decides continuation from
        # accepted_goals, not from ok.
        super().finalize_result(ok=bool(self.result.accepted_goals or payload))

    def process_parse_result(
        self, parse_result: GoalParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if len(parse_result.system_goals) == 0 and not parse_result.out_of_scope:
            logger.warning("Nothing was classified in the initial parse")
            self.record.ok = False
            self.record.add_details("Nothing was classified in the initial parse")
            raise RuntimeError("Nothing was classified in the initial parse")

        self.result.out_of_scope = parse_result.out_of_scope

        # overflow goals are valid, just over the model's limit — run them
        # through the same checks so they can fill capacity freed by refusals,
        # or wait in buffer_goals
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
