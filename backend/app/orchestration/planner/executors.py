import logging

from app.common.prompt_loader import load_prompt
from .schemas import InitialParseNode, InitialParseResult

from app.common.sse_stream import SSEStream
from clients.schemas import OpenAIParserRequest

from common.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from common.operation import run_tool_call

logger = logging.getLogger(__name__)

class InitialParseWorkflow(Workflow[InitialParseResult]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"
    
    system_prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_system.txt")
    user_prompt = load_prompt(prompt_path="orchestration/planner/prompts/initial_parse_response.txt")
    
    output_schema = InitialParseResult
    tool_models = [InitialParseNode]
    
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(output_type=self.output_schema)
        
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
        
        
    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")    

        # Use pipeline conversation for internal LLM calls
        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[self.user_message],
            tool_models=self.tool_models,
        )
        llm_result = await self.llm_client.execute_new(req)
        self.add_step(llm_result)
        assistant_msg = llm_result.result
        
        tool_message = await run_tool_call(assistant_msg.tool_calls[0])
        self.add_step(tool_message)
        
        parse_result = tool_message.result

        self.result.result = parse_result
        self.result.ok = bool(parse_result.continue_pipeline and parse_result.user_query_domain)
        self.result.message = self.success_message if self.result.ok else self.failure_message
        
        await self.generate_user_response(
            parse_result.to_llm_messages(), 
            prompt=self.user_prompt, 
            sse_stream=self.sse_stream
        )
        