from typing import cast

from .parse_intent import SystemGoal
from app.common.prompt_loader import format_prompt, load_prompt

from app.domains.base_request import BaseRequest
from app.domains.node_types import NodeTypeEnum
from app.registry import NODE_TYPE_TO_CLS
from clients import OpenAIParserRequest
from clients.base import BaseLLMClient
from clients.openai_requests import OpenAIChatRequest
from app.common.messages import AssistantMessage

ARG_PARSER_PROMPT_PATH = "domains/planner/prompts/1_argument_parser.txt"


async def parse_argument(goal: SystemGoal, llm_client: BaseLLMClient) -> BaseRequest:
    if not goal or not llm_client:
        raise ValueError("input error")
    
    system_prompt = load_prompt(prompt_path=ARG_PARSER_PROMPT_PATH)
    tool = NODE_TYPE_TO_CLS[goal.target_node_type]
    message = AssistantMessage(content=goal.description)
    
    req = OpenAIParserRequest(
        prompt=system_prompt,
        model="gpt-5.6-luna",
        reasoning_effort = "none",
        # NOTE: this should be a list of previous messages as well
        # but for now we can just do clear and direct instructions
        messages=[message],
        tool_models=[tool],
    )
    assistant_msg = await llm_client.execute(req, save_payload=True)
    assistant_msg = assistant_msg.output
    tool_calls = assistant_msg.tool_calls
    if not tool_calls:
        # previously an unguarded [0] on None — same failure semantics
        # (runtime error caught by the workflow), clearer message
        raise ValueError("LLM response contained no tool calls")

    # parsed_arguments is typed `object | None` by the openai lib; the parser
    # validated it against `tool`, a BaseRequest subclass, so the cast holds.
    # Return the request itself, not the tool-call wrapper — callers set the
    # private _id / _depends_on on it, and those silently no-op on the wrapper.
    parsed = tool_calls[0].function.parsed_arguments
    if parsed is None:
        raise ValueError(f"LLM tool call for {goal.target_node_type} had no parsed arguments")
    
    request = cast(BaseRequest, parsed)
    request._id = goal.id
    request._depends_on = goal.depends_on.copy()
    return request
