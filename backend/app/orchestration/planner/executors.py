import json
from clients import OpenAIRequest
from app.common.messages import SystemMessage, AssistantMessage
from app.common.prompt_loader import load_prompt, format_prompt
from openai import pydantic_function_tool
from app.orchestration.request_context import RequestContext
from .schemas import InitialParseNode, InitialParseResult, BookClassificationNode, BookClassificationResult, TaskGenerationNode, TaskPlan

async def run_initial_step(request_context, sse_stream) -> str | None:
    """Run the initial parsing step to determine if the query is in-scope."""
    
    from app.orchestration.orchestrator import Orchestrator
    orchestrator = Orchestrator()

    await sse_stream.send_ui_loading("Thinking...")

    tool_name = InitialParseNode.__name__
    tool = pydantic_function_tool(
        InitialParseNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    tool_choice = {"type": "function", "function": {"name": tool_name}}
    # Set current step for tracking
    request_context.set_current_step("initial_parse")

    # Use pipeline conversation for internal LLM calls
    pipeline_messages = request_context.get_conversation_for_llm(
        include_pipeline=True
    )

    prompt = load_prompt(prompt_path="planner/prompts/initial_system.txt")
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=pipeline_messages,
        tools=[tool],
        tool_choice=tool_choice,
        temperature=0.3,
        top_p=0.8,
    )
    assistant_msg = await request_context.llm_client.execute(req)
    # this shouldn't happen at all but raise to be safe
    if not assistant_msg or not assistant_msg.tool_calls:
        raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")

    # Add to pipeline conversation (internal)
    request_context.add_message(assistant_msg)
    tool_message = await orchestrator.handle_tool_call(
        assistant_msg.tool_calls, max_calls=1
    )

    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    # Add tool response to pipeline conversation
    request_context.add_message(tool_message[0])

    # Store the result for later use
    parse_result = tool_message[0].content
    request_context.set_step_result("initial_parse", parse_result)

    no_in_domain_msg = tool_message[0].content.model_dump_json(
        include={"small_talk", "out_of_scope", "continue_pipeline"}
    )

    prompt = load_prompt(prompt_path="planner/prompts/initial_parse_response.txt")
    req = OpenAIRequest(
        system=SystemMessage(content=prompt),
        messages=[AssistantMessage(content=no_in_domain_msg)],
        sse_stream=sse_stream,
        temperature=0.7,
        top_p=1.0,
    )

    response = await request_context.llm_client.execute(req)

    await sse_stream.send_divider()

    request_context.add_message(response)

    return tool_message[0].content

async def run_analyze_classification(
    request_context: RequestContext,
    initial_parse_result: InitialParseResult,
) -> BookClassificationResult:
    """Classify the user query into book-related strategies."""
    
    from app.orchestration.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    
    tool_name = BookClassificationNode.__name__
    tool = pydantic_function_tool(
        BookClassificationNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    tool_choice = {"type": "function", "function": {"name": tool_name}}

    in_domain_msg = initial_parse_result.model_dump_json(
        include={"user_query_domain", "continue_pipeline", "reasoning"}
    )

    from config import BookConstraints, BookGuides

    prompt = format_prompt(
        prompt_path="books/prompts/strategy_classification.txt",
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

    # req.export(file_name="analyze_classification")

    assistant_msg = await request_context.llm_client.execute(req)

    if not assistant_msg or not assistant_msg.tool_calls:
        raise RuntimeError(
            f"Failed to execute {tool_name} - no tool calls received"
        )

    request_context.add_message(assistant_msg)
    tool_message = await orchestrator.handle_tool_call(
        assistant_msg.tool_calls, max_calls=1
    )
    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    request_context.add_message(tool_message[0])

    # we know for a fact it must have the fragments here
    return tool_message[0].content

async def run_create_task_plan(
    request_context: RequestContext,
    initial_parse_result: InitialParseResult,
    node_ids,
) -> TaskPlan:
    """Create a task execution plan with dependency resolution."""

    from app.orchestration.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    
    tool_name = TaskGenerationNode.__name__
    tool_choice = {"type": "function", "function": {"name": tool_name}}
    tool = pydantic_function_tool(
        TaskGenerationNode,
        name=tool_name,
        description=f"Fill the schema for {tool_name}",
    )
    TaskGenerationNode.modify_schema(tool=tool, valid_ids=list(node_ids.keys()))

    in_domain_msg = initial_parse_result.model_dump_json(
        include={"user_query_domain", "reasoning"}
    )

    formatted_node_ids = {}
    for id in node_ids:
        formatted_node_ids[id] = node_ids[id].model_dump()

    prompt = load_prompt(prompt_path="planner/prompts/dependency_resolution.txt")
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

    request_context.add_message(assistant_msg)
    tool_message = await orchestrator.handle_tool_call(
        assistant_msg.tool_calls, max_calls=1, node_ids=node_ids
    )
    if not tool_message:
        raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

    request_context.add_message(tool_message[0])

    return tool_message[0].content