from pydantic import BaseModel, Field
from typing import List
from app.domains.books.schemas import ClassificationStrategy


class StrategyClassificationResult(BaseModel):
    """Generic classification result for any node type."""
    accepted: List[ClassificationStrategy] = []
    refused: List[ClassificationStrategy] = []
    continue_pipeline: bool = False
    
    def get_accepted_node_ids(self):
        """Return dict of node_id -> serialized node data."""
        return {node.id: node for node in self.accepted}


class StrategyClassificationNode(BaseModel):
    """Classification node specifically for book domain strategies."""
    strategies: List[ClassificationStrategy] = Field(
        ...,
        max_length=15,
        description="List of strategies generated from the query")

    async def __call__(self, accepted_tuning: float = 0.7):
        """Convert to ClassificationResult format"""        
        result = StrategyClassificationResult()
        
        for strategy in self.strategies:
            if strategy.refusal or strategy.confidence < accepted_tuning:
                result.refused.append(strategy)
            else:
                result.accepted.append(strategy)

        result.continue_pipeline = bool(len(result.accepted) > 0)
        return result
    
# @task
# async def run_analyze_classification(
#     request_context: RequestContext,
#     initial_parse: InitialParseResult,
# ) -> OperationResult:
#     """Classify the user query into book-related strategies."""
#     steps = []
#     tool_name = BookClassificationNode.__name__
#     tool = pydantic_function_tool(
#         BookClassificationNode,
#         name=tool_name,
#         description=f"Fill the schema for {tool_name}",
#     )
#     tool_choice = {"type": "function", "function": {"name": tool_name}}

#     in_domain_msg = initial_parse.model_dump_json(
#         include={"user_query_domain", "continue_pipeline", "reasoning"}
#     )

#     from config import BookConstraints, BookGuides

#     prompt = format_prompt(
#         prompt_path="domains/books/prompts/strategy_classification.txt",
#         book_constraints=str(BookConstraints()),
#         book_guides=str(BookGuides()),
#     )
#     req = OpenAIRequest(
#         system=SystemMessage(content=prompt),
#         messages=[AssistantMessage(content=in_domain_msg)],
#         tools=[tool],
#         tool_choice=tool_choice,
#         temperature=0.4,
#         top_p=0.5,
#     )

#     result = await request_context.llm_client.execute_new(req)
#     steps.append(result)
#     if not result.ok:
#         raise RuntimeError(f"🛑 {tool_name} parse {tool_name} FAILED")
#         ...

#     assistant_msg = result.result

#     if not assistant_msg or not assistant_msg.tool_calls:
#         raise RuntimeError(
#             f"Failed to execute {tool_name} - no tool calls received"
#         )

#     # request_context.add_message(assistant_msg) #TODO: add to conversation
#     tool_message = await handle_tool_call(
#         assistant_msg.tool_calls, max_calls=1
#     )
#     if not tool_message:
#         raise RuntimeError(f"🛑 {tool_name} call {tool_message} FAILED")

#     # request_context.add_message(tool_message[0]) #TODO: add to conversation

#     # we know for a fact it must have the fragments here
#     return OperationResult(
#         name="analyze_classification",
#         steps=steps,
#         ok=True,
#         message="Analysis completed successfully",
#         result=tool_message[0].content,
#     )
    
from common.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import AssistantMessage, BaseMessage
from clients.openai_client import OpenAIClient
from common.operation import OperationResult, task
from app.common.prompt_loader import format_prompt
from clients.schemas import OpenAIRequest
from config import BookConstraints, BookGuides
from app.orchestration.planner import InitialParseResult
from clients.schemas import OpenAIParserRequest
from common.operation import run_tool_call

class StrategyClassificationWorkflow(Workflow[StrategyClassificationResult]):
    success_message = "Strategy classification completed successfully"
    failure_message = "Strategy classification failed"
    
    system_prompt = format_prompt(
        prompt_path="domains/books/prompts/strategy_classification.txt",
        book_constraints=str(BookConstraints()),
        book_guides=str(BookGuides()),
    )
    
    tool_models = [StrategyClassificationNode]
    
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(output_type=StrategyClassificationResult)
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
    async def run(self, initial_parse: InitialParseResult) -> StrategyClassificationResult:    
        """Classify the user query into book-related strategies."""        

        in_domain_msg = initial_parse.model_dump_json(
            include={"user_query_domain", "continue_pipeline", "reasoning"}
        )
        
        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[AssistantMessage(content=in_domain_msg)],
            tool_models=self.tool_models,
        )
        llm_result = await self.llm_client.execute_new(req)
        self.result.steps.append(llm_result)
        
        assistant_msg = llm_result.result
        
        tool_message = await run_tool_call(assistant_msg.tool_calls[0])
        self.result.steps.append(tool_message)
        
        classification_result = tool_message.result
        self.result.result = classification_result
        self.result.ok = bool(classification_result.continue_pipeline)
        self.result.message = self.success_message if self.result.ok else self.failure_message
        
        if classification_result.refused:
            # TODO: handle refused strategies (UI message or re-classification)
            ...
            