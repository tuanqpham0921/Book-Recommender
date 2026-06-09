import json
from clients import OpenAIRequest
from app.common.messages import SystemMessage, AssistantMessage
from app.common.prompt_loader import load_prompt, format_prompt
from openai import pydantic_function_tool
from app.orchestration.request_context import RequestContext
from .schemas import InitialParseNode, InitialParseResult, BookClassificationNode, BookClassificationResult, TaskGenerationNode, TaskPlan
from app.common.messages import ToolMessage
import logging
import time
from app.common.sse_stream import SSEStream

from common.operation import task, OperationResult

logger = logging.getLogger(__name__)

async def handle_tool_call(
       tool_calls, max_calls: int = 10, **extra_kwargs
) -> list[ToolMessage]:
    """Execute tool calls and return the results."""
    results = []
    for tool_call in tool_calls[:max_calls]:
        try:

            tool_name = tool_call.function.name
            tool_id = tool_call.id
            logger.info(f"🔧 Starting tool call: {tool_name} (id: {tool_id})")

            raw_args = json.loads(tool_call.function.arguments)
            tool_instance = tool_call.function.parsed_arguments

            start = time.monotonic()
            # logger.info(f"⚡ Executing {tool_name} with args: {raw_args}")
            logger.info(f"⚡ Executing {tool_name}")

            result = await tool_instance(**extra_kwargs)
            elapsed = round(time.monotonic() - start, 2)

            logger.info(f"✅ Tool {tool_name} completed successfully in {elapsed}s")

            results.append(
                ToolMessage(
                    name=tool_call.function.name,
                    tool_call_id=tool_call.id,
                    content=result,
                    elapsed=elapsed,
                )
            )
        except json.JSONDecodeError as e:
            logger.error(f"🛑 JSON parsing failed for tool {tool_name}: {e}")
            continue
        except Exception as e:
            logger.error(
                f"🛑 Tool execution failed for {tool_name}: {e}", exc_info=True
            )
            continue

    return results

@task
async def run_initial_step(request_context: RequestContext, sse_stream: SSEStream) -> OperationResult:
    """Run the initial parsing step to determine if the query is in-scope."""
    # conversation = [request_context.user_message]
    steps = []
    await sse_stream.send_ui_loading("Thinking...")    

    tool_name = InitialParseNode.__name__
    tool = pydantic_function_tool(
        InitialParseNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    tool_choice = {"type": "function", "function": {"name": tool_name}}

    # Use pipeline conversation for internal LLM calls

    prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_system.txt")
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=[request_context.user_message],
        tools=[tool],
        tool_choice=tool_choice,
        temperature=0.3,
        top_p=0.8,
    )
    result = await request_context.llm_client.execute_new(req)
    steps.append(result)
    
    if not result.ok:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
        ...
        
    assistant_msg = result.result
    
    tool_instance = assistant_msg.tool_calls[0].function.parsed_arguments
    tool_message = await tool_instance()

    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    # Add tool response to pipeline conversation
    #TODO: add to conversation
    # conversation.append(tool_message[0])

    # Store the result for later use
    parse_result = tool_message.content

    no_in_domain_msg = tool_message.content.model_dump_json(
        include={"small_talk", "out_of_scope", "continue_pipeline"}
    )

    # user facing response
    prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_parse_response.txt")
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=[AssistantMessage(content=no_in_domain_msg)],
        sse_stream=sse_stream,
        temperature=0.7,
        top_p=1.0,
    )

    result = await request_context.llm_client.execute_new(req)
    steps.append(result)
    if not result.ok:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
        ...

    await sse_stream.send_divider()
        
    ok = bool(parse_result.continue_pipeline and parse_result.user_query_domain)
    message = "Initial parse completed successfully" if ok else "Initial parse failed"

    return OperationResult(
        name="initial_parse",
        steps=steps,
        ok=ok,
        message=message,
        result=parse_result,
    )
    

from app.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
class InitialParseWorkflow(Workflow):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__()
        
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
        
    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")    

        tool_name = InitialParseNode.__name__
        tool = pydantic_function_tool(
            InitialParseNode,
            name=tool_name,
            description=f"Fill the schema for {tool_name}",
        )
        tool_choice = {"type": "function", "function": {"name": tool_name}}

        # Use pipeline conversation for internal LLM calls

        prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_system.txt")
        req = OpenAIRequest(
            system=SystemMessage(content=prompt),
            messages=[self.user_message],
            tools=[tool],
            tool_choice=tool_choice,
            temperature=0.3,
            top_p=0.8,
        )
        result = await self.llm_client.execute_new(req)
        self.add_step(result)
        
        if not result.ok:
            raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
            ...
            
        assistant_msg = result.result
        
        tool_instance = assistant_msg.tool_calls[0].function.parsed_arguments
        tool_message = await tool_instance()

        if not tool_message:
            raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

        # Add tool response to pipeline conversation
        #TODO: add to conversation
        # conversation.append(tool_message[0])

        # Store the result for later use
        parse_result = tool_message

        no_in_domain_msg = tool_message.model_dump_json(
            include={"small_talk", "out_of_scope", "continue_pipeline"}
        )

        # user facing response
        prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_parse_response.txt")
        req = OpenAIRequest(
            system=SystemMessage(content=prompt),
            messages=[AssistantMessage(content=no_in_domain_msg)],
            sse_stream=self.sse_stream,
            temperature=0.7,
            top_p=1.0,
        )

        result = await self.llm_client.execute_new(req)
        self.add_step(result)
        if not result.ok:
            raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
            ...

        await self.sse_stream.send_divider()
        
        self.result.ok = bool(parse_result.continue_pipeline and parse_result.user_query_domain)
        self.result.message = self.success_message if self.result.ok else self.failure_message
        self.result.result = parse_result
        # ok = bool(parse_result.continue_pipeline and parse_result.user_query_domain)
        # message = "Initial parse completed successfully" if ok else "Initial parse failed"

        # return self.result