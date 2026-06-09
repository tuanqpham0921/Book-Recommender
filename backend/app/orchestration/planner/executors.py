import json
from clients import OpenAIRequest
from app.common.messages import SystemMessage, AssistantMessage
from app.common.prompt_loader import load_prompt
from openai import pydantic_function_tool
from .schemas import InitialParseNode, InitialParseResult
import logging
from app.common.sse_stream import SSEStream
from clients.schemas import OpenAIParserRequest, OpenAIChatRequest
logger = logging.getLogger(__name__)

from app.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from common.operation import task, OperationResult
from typing import Any

@task
async def run_tool_call(tool_call, **kwargs) -> OperationResult[Any]:
    tool_name = tool_call.function.name
    
    tool_instance = tool_call.function.parsed_arguments
    output = await tool_instance(**kwargs)
    return OperationResult(
        name=tool_name,
        ok=True,
        message=f"{tool_name} completed successfully",
        result=output,
        output_type=type(output),
    )


class InitialParseWorkflow(Workflow[InitialParseResult]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    
    system_prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_system.txt")
    user_prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_parse_response.txt")
    
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(output_type=InitialParseResult)
        
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
        
    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")    

        # Use pipeline conversation for internal LLM calls
        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[self.user_message],
            tool_models=[InitialParseNode],
        )
        llm_result = await self.llm_client.execute_new(req)
        self.add_step(llm_result)
        assistant_msg = llm_result.result
        
        tool_message = await run_tool_call(assistant_msg.tool_calls[0])
        self.add_step(tool_message)

        # Store the result for later use
        parse_result = tool_message.result
        no_in_domain_msg = tool_message.result.model_dump_json(
            include={"small_talk", "out_of_scope", "continue_pipeline"}
        )

        # user facing response
        prompt = self.user_prompt
        req = OpenAIChatRequest(
            prompt=prompt,
            messages=[AssistantMessage(content=no_in_domain_msg)],
            sse_stream=self.sse_stream,
            temperature=0.7,
            top_p=1.0,
        )
        result = await self.llm_client.execute_new(req)
        self.add_step(result)
        
        self.result.ok = bool(parse_result.continue_pipeline and parse_result.user_query_domain)
        self.result.message = self.success_message if self.result.ok else self.failure_message
        self.result.result = parse_result