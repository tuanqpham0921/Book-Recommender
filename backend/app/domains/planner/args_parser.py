from typing import cast

from .parse_intent import SystemGoal
from app.common.prompt_loader import format_prompt, load_prompt

from app.domains.base_request import BaseRequest
from app.domains.node_types import NodeTypeEnum
from app.registry import NODE_TYPE_TO_CLS
from clients import OpenAIParserRequest
from clients.openai_requests import OpenAIChatRequest
from app.common.messages import AssistantMessage

ARG_PARSER_PROMPT_PATH = "domains/planner/prompts/1_argument_parser.txt"


# The LLM call itself is deliberately not made here: the caller runs it through
# run_async_step so the call lands in the workflow's steps and its tokens roll
# up into the workflow's token_usage. Awaiting llm_client.execute() directly
# would discard that envelope and lose the spend.
def build_arg_parser_request(goal: SystemGoal) -> OpenAIParserRequest:
    """Build the LLM request that fills in one goal's typed arguments, using
    the goal's normalized description as the instruction and the goal's target
    node type as the only offered tool."""
    if not goal:
        raise ValueError("input error")

    system_prompt = load_prompt(prompt_path=ARG_PARSER_PROMPT_PATH)
    tool = NODE_TYPE_TO_CLS[goal.target_node_type]
    message = AssistantMessage(content=goal.description)

    return OpenAIParserRequest(
        prompt=system_prompt,
        model="gpt-5-nano",
        reasoning_effort="minimal",
        # NOTE: this should be a list of previous messages as well
        # but for now we can just do clear and direct instructions
        messages=[message],
        tool_models=[tool],
        # The goal already picked the node type and tool_choice pins it, so the
        # class docstring — which is there to help the planner choose between
        # tools — would only be noise here. Field descriptions still ship.
        include_tool_description=False,
    )


def extract_parsed_request(
    goal: SystemGoal, assistant_msg: AssistantMessage
) -> BaseRequest:
    """Pull the validated node request out of the tool call and stamp it with
    the plan ids from the goal that produced it."""
    tool_calls = assistant_msg.tool_calls
    if not tool_calls:
        # previously an unguarded [0] on None — same failure semantics
        # (runtime error caught by the workflow), clearer message
        raise ValueError("LLM response contained no tool calls")

    # parsed_arguments is typed `object | None` by the openai lib; the parser
    # validated it against `tool`, a BaseRequest subclass, so the cast holds.
    # Return the request itself, not the tool-call wrapper — we set the private
    # _id / _depends_on on it, and those silently no-op on the wrapper.
    parsed = tool_calls[0].function.parsed_arguments
    if parsed is None:
        raise ValueError(
            f"LLM tool call for {goal.target_node_type} had no parsed arguments"
        )

    request = cast(BaseRequest, parsed)
    request._id = goal.id
    request._depends_on = goal.depends_on.copy()
    return request
