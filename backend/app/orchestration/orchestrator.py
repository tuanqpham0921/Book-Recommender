import json
import logging
import asyncio
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import ToolMessage
from app.domains.books.strategies import BOOK_STRAT_REGISTRY

from common.operation import OperationResult, task
from common.utils import save_file
from app.orchestration.planner import InitialParseWorkflow
logger = logging.getLogger(__name__)

from common.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient
from app.orchestration.planner import StrategyClassificationWorkflow
from app.orchestration.planner import TaskPlanWorkflow
class ConversationOrchestrator(Workflow[None]):
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(output_type=None)
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
    async def run(self, request_context: RequestContext) -> None:
        initial_parse = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        initial_parse_result = await self.run_async_step(initial_parse())
        await self.sse_stream.send_divider()
        
        in_domain_message = initial_parse_result.output.model_dump_json(
            include={"user_query_domain", "continue_pipeline", "reasoning"}
        )
        request_context.in_domain_message = in_domain_message
        
        strategy_classification = StrategyClassificationWorkflow(self.sse_stream, self.user_message, self.llm_client)
        strategy_classification_result = await self.run_async_step(
            strategy_classification(in_domain_message)
        )
        
        node_ids = strategy_classification_result.output.get_accepted_node_ids()
        if not node_ids:
            raise RuntimeError("No accepted node ids")
        
        task_planner = TaskPlanWorkflow(self.sse_stream, self.user_message, self.llm_client)
        task_planner_result = await self.run_async_step(
            task_planner(in_domain_message, node_ids)
        )
        if not task_planner_result.ok:
            # TODO: test and get an openai error message for this
            # need to pass in details and context to the error message
            await self.sse_stream.send_error(task_planner_result.message)
            return
        
        await self.sse_stream.send_divider()
        
        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
        
    
class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        """Initialize the orchestrator."""
        pass
    
    async def _run_conversation_step(self, request_context: RequestContext, sse_stream: SSEStream):
        conversation_orchestrator = ConversationOrchestrator(sse_stream, request_context.user_message, request_context.llm_client)
        await conversation_orchestrator(request_context=request_context)
        return conversation_orchestrator.result

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""
        sse_stream = request_context.sse_stream
        result = None
        try:
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            result = await self._run_conversation_step(request_context, sse_stream)

            # Normal completion
            await sse_stream.send("complete", {"status": "completed"})
            logger.info("✅ Orchestration completed successfully")

        except Exception as e:
            logger.exception(f"❌ Unhandled orchestrator error: {e}")
            # await sse_stream.send_error(f"Internal error: {str(e)}")
            await sse_stream.send_error(
                f"Hmm... something went wrong while processing your query."
            )

        finally:
            if result is not None:
                save_file(result, file_name=f"orchestration_result-dev")
            await sse_stream.close()
