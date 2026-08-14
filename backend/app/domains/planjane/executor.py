import logging

from clients.messages import UserMessage
from app.common.prompt_loader import format_prompt
from app.domains.base_workflow import AppWorkflow
from app.domains.node_input import NodeInput, ParsedInput
from app.registry import REGISTRY
from clients import OpenAIParserRequest

from app.domains.planjane.dial.mermaid import get_goals_mermaid_diagram
from .external import PlanJaneOutput
from .schemas import MAX_SYSTEM_GOALS, GoalParseRequest

logger = logging.getLogger(__name__)

# The planner is reachable from both ends: the user's text, or the tool schema
# already filled in (see `GoalParseRequest.__call__`).
PlanJaneInput = NodeInput | ParsedInput[GoalParseRequest]

GOAL_GENERATOR_PROMPT_PATH = "domains/planjane/prompts/0_goal_generator.txt"
# PLAYGORUND_PROMPT_PATH = "../playground/prompting/planner_prompt._extended.txt"


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

    async def _run_llm_args_parse(self, query: str) -> GoalParseRequest:
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
        parse_result = await self.run_llm_args_parse(req)
        return parse_result

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