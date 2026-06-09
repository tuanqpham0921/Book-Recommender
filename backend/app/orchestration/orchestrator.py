import json
import logging
import asyncio
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import ToolMessage
from .planner.schemas import TaskPlan
from app.domains.books.strategies import BOOK_STRAT_REGISTRY

from common.operation import OperationResult, task
from common.utils import save_file
from app.orchestration.planner.executors import InitialParseWorkflow
logger = logging.getLogger(__name__)

from app.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient

class ConversationOrchestrator(Workflow[None]):
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__(output_type=None)
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
    async def run(self, request_context: RequestContext) -> None:
        initial_parse = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        initial_parse_result = await initial_parse()
        self.add_step(initial_parse_result)
        if not initial_parse_result.ok or initial_parse_result.result is None:
            self.result.ok = False
            self.result.message = "Initial parse failed"
            return
        
        await self.sse_stream.send_divider()
        
        request_context.in_domain_message = (
            initial_parse_result.result.model_dump_json(
                include={"user_query_domain", "continue_pipeline", "reasoning"}
            )
        )
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
