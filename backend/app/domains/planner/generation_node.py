from pydantic import BaseModel, Field
from .parse_intent import SystemGoal
from app.common.messages import UserMessage, AssistantMessage
from clients import OpenAIParserRequest
from common.utils import to_serializable


system_prompt = "domains/planner/prompts/generation_node.txt"


class section(BaseModel):
    
    query_portion: str = Field(..., description="portion of the user message to answer")
    depends_on: list[str] = Field(..., description="the goal id where this query will generate text")

class GenerationNode(BaseModel):
    sections: list[section] = Field(..., description="list of sections of the query")
    
    
async def create_generation_node(
    goals: SystemGoal, user_msg: UserMessage, llm_client
) -> GenerationNode:
    req = OpenAIParserRequest(
        prompt=system_prompt,
        model="gpt-5-nano",
        reasoning_effort="medium",
        messages=[user_msg, AssistantMessage(to_serializable(goals))],
        tool_models=[GenerationNode],
    )
    
    assistant_msg = await llm_client.execute(req)
    tool_calls = assistant_msg.tool_calls
    if not tool_calls:
        # previously an unguarded [0] on None — same failure semantics
        # (runtime error caught by the workflow), clearer message
        raise ValueError("LLM response contained no tool calls")

    parsed = tool_calls[0].function.parsed_arguments
    
    from common.utils import print_json
    print_json(parsed)

    return parsed
