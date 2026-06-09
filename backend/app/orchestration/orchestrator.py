import json
import logging
import asyncio
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import ToolMessage
from .planner.schemas import TaskPlan
from .planner.executors import run_initial_step
from app.domains.books.strategies import BOOK_STRAT_REGISTRY

from common.operation import OperationResult, task
from common.utils import save_file
from app.orchestration.planner.executors import InitialParseWorkflow
logger = logging.getLogger(__name__)

from app.workflow import Workflow
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient

class ConversationOrchestrator(Workflow):
    def __init__(self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient):
        super().__init__()
        self.sse_stream = sse_stream
        self.user_message = user_message
        self.llm_client = llm_client
        
    async def run(self, request_context: RequestContext) -> OperationResult:
        initial_parse = InitialParseWorkflow(self.sse_stream, self.user_message, self.llm_client)
        initial_parse_result = await initial_parse()
        self.add_step(initial_parse_result)
        
        request_context.in_domain_message = (
            initial_parse_result.result.model_dump_json(
                include={"user_query_domain", "continue_pipeline", "reasoning"}
            )
        )
        return self.result

class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        """Initialize the orchestrator."""
        # Here you can initialize any resources that are needed for the orchestrator
        # like saving logs to a file or a database
        # update user info after each request
        # this is one App level resource that can be used by all requests
        # so it will hold references that are needed for the resources managed by the orchestrator
        # self.log_session_factory = None
        pass
    
    # @task
    # async def _run_conversation_step(
    #     self,
    #     request_context: RequestContext,
    #     sse_stream: SSEStream,
    # ) -> OperationResult:
    #     """Execute the complete conversation pipeline from parsing to task execution."""
    #     steps = []
        
    #     initial_parse = await run_initial_step(request_context, sse_stream)
    #     steps.append(initial_parse)
    #     if initial_parse.run_time_error:
    #         #TODO: handle out of scope or no domain identified
    #         ... 
    #     # ----------------------------------------------------------

    #     request_context.in_domain_message = (
    #         initial_parse.result.model_dump_json(
    #             include={"user_query_domain", "continue_pipeline", "reasoning"}
    #         )
    #     )
        
    #     return OperationResult(
    #         name="run_tasks",
    #         ok=True,
    #         steps=steps,
    #         message="Tasks executed successfully.",
    #         details={"user_input": request_context.user_message}
    #     )

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
