import logging

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext

from app.domains.planner import ConversationOrchestrator
from app.orchestration.run_recorder import record_chat_run

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        """Initialize the orchestrator."""
        pass

    async def _run_conversation_step(self, request_context: RequestContext, sse_stream: SSEStream):
        conversation_orchestrator = ConversationOrchestrator(sse_stream, request_context.user_message, request_context.llm_client)
        await conversation_orchestrator(request_context=request_context)
        return conversation_orchestrator

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""
        sse_stream = request_context.sse_stream
        try:
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            conversation_orchestrator = await self._run_conversation_step(request_context, sse_stream)
            if conversation_orchestrator.result is not None:
                await record_chat_run(request_context, conversation_orchestrator)
            # Normal completion — chat_id lets the client attach feedback
            # to the chat_runs row recorded above
            await sse_stream.send(
                "complete",
                {"status": "completed", "chat_id": request_context.user_message.id},
            )
            logger.info("✅ Orchestration completed successfully")

        except Exception as e:
            logger.exception(f"❌ Unhandled orchestrator error: {e}")
            # await sse_stream.send_error(f"Internal error: {str(e)}")
            await sse_stream.send_error(
                f"Hmm... something went wrong while processing your query."
            )

        await sse_stream.close()
