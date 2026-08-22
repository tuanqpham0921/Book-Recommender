"""The planner's flow. `run` is the table of contents; everything else sits
where the flow reaches it.

Same reading rule as the book slices (domains/README.md;
`books/find_similar_books/executor.py` is the worked example): this file is the
flow — `run()` plus every step, methods in the order `run` reaches them — with
the request builder as a module-level pure function beside it. The satellites
hold what outlives the run: `schemas.py` is what the LLM fills in,
`external.py` is what the plan *is*, `dial/` is how the plan is shown.
"""

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


def build_goal_parse_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to break the message into `GoalParseRequest` goals.

    The one request in the app whose prompt embeds the live tool catalog, and
    the reason accuracy outranks cost on the model choice: the planner sees
    every capability, the cache hit rate is high, and the output is short.
    """
    if not query:
        raise ValueError("No query to plan from")

    system_prompt = format_prompt(
        prompt_path=GOAL_GENERATOR_PROMPT_PATH,
        TOOLS_NAME_DESCRIPTION=REGISTRY.format_catalog(),
    )
    # NOTE: toggle on for prompting experiments
    # system_prompt = load_prompt(prompt_path=PLAYGORUND_PROMPT_PATH)

    return OpenAIParserRequest(
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


class PlanJaneExecutor(AppWorkflow[PlanJaneOutput]):
    ui_loading_message = "Thinking..."
    intent_reject_message = (
        "I can't help with that request. Please try again with a book-related question."
    )
    continuation_reject_message = "I don't have memory of earlier messages yet — please restate your full request in one message."

    async def run(self, node_input: PlanJaneInput) -> None:
        """Two ways in, one body.

        From natural language (`NodeInput`) the planner makes the tool call
        itself; handed an already-filled `GoalParseRequest` it skips to the
        processing. Everything after the branch is shared, which is the point —
        the tool schema can be exposed and called directly without a second
        implementation of what happens to the goals.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. parse the message into goals — or take them already parsed
        if isinstance(node_input, NodeInput):
            parse_result: GoalParseRequest = await self.run_llm_args_parse(
                build_goal_parse_request(node_input.query)
            )
        else:
            # already validated as GoalParseRequest by the field's annotation
            parse_result = node_input.parsed_result

        # 2. sort the goals into accepted / refused / buffered
        self.process_parse_result(parse_result)

        # 3. show the plan — the diagram is the plan rendered
        # TODO: generate an "unable to help with" reply for the refused half
        if self.result.accepted_goals:
            await self.send_mermaid(self.result.accepted_goals)

        # 4. last: ok is read off the sorted goals
        self.finalize_result()

    def process_parse_result(
        self, parse_result: GoalParseRequest, confident_tuning: float = 0.5
    ) -> None:
        if len(parse_result.system_goals) == 0 and not parse_result.out_of_scope:
            # raise, not record.ok = False — the envelope stamps the failure
            msg = "Nothing was classified in the initial parse"
            logger.warning(msg)
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

    def finalize_result(self) -> None:
        # ok = a plan came out of this turn. Continuation is still decided
        # from accepted_goals, not from ok.
        super().finalize_result(ok=bool(self.result.accepted_goals))
