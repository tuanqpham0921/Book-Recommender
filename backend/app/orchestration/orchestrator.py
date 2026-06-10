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
        initial_parse_result = await self._run_initial_parse()
        await self.sse_stream.send_divider()
        
        request_context.in_domain_message = (
            initial_parse_result.result.model_dump_json(
                include={"user_query_domain", "continue_pipeline", "reasoning"}
            )
        )
        
        strategy_classification_result = await self._run_strategy_classification(initial_parse_result)
        
        task_planner_result = await self._run_task_planner(initial_parse_result, strategy_classification_result)
    
        
        await self.sse_stream.send_divider()
        
        self.result.ok = True
        self.result.message = "Conversation orchestration completed successfully"
        
    async def _run_initial_parse(self):
        initial_parse = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        initial_parse_result = await initial_parse()
        self.add_step(initial_parse_result)
        if not initial_parse_result.ok or initial_parse_result.result is None:
            raise RuntimeError("Initial parse failed")
        return initial_parse_result
    
    async def _run_strategy_classification(self, initial_parse_result: InitialParseWorkflow):
        strategy_classification = StrategyClassificationWorkflow(self.sse_stream, self.user_message, self.llm_client)
        strategy_classification_result = await strategy_classification(initial_parse_result.result)
        
        self.add_step(strategy_classification_result)
        if strategy_classification_result.result is None or not strategy_classification_result.result.continue_pipeline:
            raise RuntimeError("Strategy classification failed")
        return strategy_classification_result
    
    async def _run_task_planner(self, initial_parse_result: InitialParseWorkflow, strategy_classification_result: StrategyClassificationWorkflow):
        task_planner = TaskPlanWorkflow(self.sse_stream, self.user_message, self.llm_client)
        task_planner_result = await task_planner(initial_parse_result.result, strategy_classification_result.result)
        
        if task_planner_result.result is None or not task_planner_result.ok:
            raise RuntimeError("Task planner failed")
        
        self.add_step(task_planner_result)
        return task_planner_result
    
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
