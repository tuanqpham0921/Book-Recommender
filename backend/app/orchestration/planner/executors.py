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
# from app.operation import ChatResult

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
    result = await request_context.llm_client.execute(req)
    steps.append(result)
    
    if not result.ok:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
        ...
        
    assistant_msg = result.result
    tool_message = await handle_tool_call(
        assistant_msg.tool_calls, max_calls=1
    )

    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    # Add tool response to pipeline conversation
    #TODO: add to conversation
    # conversation.append(tool_message[0])

    # Store the result for later use
    parse_result = tool_message[0].content

    no_in_domain_msg = tool_message[0].content.model_dump_json(
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

    result = await request_context.llm_client.execute(req)
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

@task
async def run_analyze_classification(
    request_context: RequestContext,
    initial_parse: InitialParseResult,
) -> OperationResult:
    """Classify the user query into book-related strategies."""
    steps = []
    tool_name = BookClassificationNode.__name__
    tool = pydantic_function_tool(
        BookClassificationNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    tool_choice = {"type": "function", "function": {"name": tool_name}}

    in_domain_msg = initial_parse.model_dump_json(
        include={"user_query_domain", "continue_pipeline", "reasoning"}
    )

    from config import BookConstraints, BookGuides

    prompt = format_prompt(
        prompt_path="domains/books/prompts/strategy_classification.txt",
        book_constraints=str(BookConstraints()),
        book_guides=str(BookGuides()),
    )
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=[AssistantMessage(content=in_domain_msg)],
        tools=[tool],
        tool_choice=tool_choice,
        temperature=0.4,
        top_p=0.5,
    )

    result = await request_context.llm_client.execute(req)
    steps.append(result)
    if not result.ok:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
        ...

    assistant_msg = result.result

    if not assistant_msg or not assistant_msg.tool_calls:
        raise RuntimeError(
            f"Failed to execute {tool_name} - no tool calls received"
        )

    # request_context.add_message(assistant_msg) #TODO: add to conversation
    tool_message = await handle_tool_call(
        assistant_msg.tool_calls, max_calls=1
    )
    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    # request_context.add_message(tool_message[0]) #TODO: add to conversation

    # we know for a fact it must have the fragments here
    return OperationResult(
        name="analyze_classification",
        steps=steps,
        ok=True,
        message="Analysis completed successfully",
        result=tool_message[0].content,
    )

@task
async def run_create_task_plan(
    request_context: RequestContext,
    initial_parse: InitialParseResult,
    classified_strategy: BookClassificationResult,
) -> OperationResult:
    """Create a task execution plan with dependency resolution."""
    
    tool_name = TaskGenerationNode.__name__
    tool_choice = {"type": "function", "function": {"name": tool_name}}
    tool = pydantic_function_tool(
        TaskGenerationNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    
    node_ids = classified_strategy.get_accepted_node_ids()
    if not node_ids:
        return OperationResult(
            name="create_task_plan",
            ok=False,
            message="No accepted node ids",
            details={"classified_strategy": classified_strategy}
        )
    
    TaskGenerationNode.modify_schema(tool=tool, valid_ids=list(node_ids.keys()))

    in_domain_msg = initial_parse.model_dump_json(
        include={"user_query_domain", "reasoning"}
    )

    formatted_node_ids = {}
    for id in node_ids:
        formatted_node_ids[id] = node_ids[id].model_dump()

    prompt = load_prompt(prompt_path="orchestration/planner/prompts/dependency_resolution.txt")
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=[
            AssistantMessage(content=in_domain_msg),
            AssistantMessage(
                content=json.dumps(formatted_node_ids, separators=(",", ":"))
            ),
        ],
        tools=[tool],
        tool_choice=tool_choice,
        temperature=0.4,
        top_p=0.5,
    )

    # req.export(file_name="task_planner")

    # initial parsing, with no streaming or content (forcing tool)
    assistant_msg = await request_context.llm_client.execute(req)

    # this shouldn't happen at all but raise to be safe
    if not assistant_msg or not assistant_msg.tool_calls:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")

    # request_context.add_message(assistant_msg) #TODO: add to conversation
    tool_message = await handle_tool_call(
        assistant_msg.tool_calls, max_calls=1, node_ids=node_ids
    )
    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    # request_context.add_message(tool_message[0]) #TODO: add to conversation
    
    return OperationResult(
        name="create_task_plan",
        ok=True,
        message="Task plan created successfully",
        result=tool_message[0].content,
    )