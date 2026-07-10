import asyncio
import logging

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext

from app.domains.planner import ConversationOrchestrator
from app.orchestration.run_recorder import record_chat_run

logger = logging.getLogger(__name__)

SAVE_LOG_TIMEOUT = 60  # seconds

class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        """Initialize the orchestrator."""
        pass

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""
        sse_stream = request_context.sse_stream
        # created (not just returned from a helper) so that a cancellation
        # mid-await below still leaves this bound for the finally block —
        # ConversationOrchestrator mutates its own .result in place and
        # re-raises on cancellation rather than returning it
        conversation_orchestrator = None
        try:
            # Sent first and unconditionally — this id is generated when the
            # user message is parsed (before any work starts), so the client
            # can attach feedback to this run even if the turn later errors,
            # times out, or is stopped before the 'complete' event fires.
            await sse_stream.send_chat_id(request_context.user_message.id)
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            conversation_orchestrator = ConversationOrchestrator(
                sse_stream, request_context.user_message, request_context.llm_client
            )
            await conversation_orchestrator(request_context=request_context)

            # Normal completion — chat_id lets the client attach feedback
            # to the chat_runs row recorded in the finally block below
            await sse_stream.send(
                "complete",
                {"status": "completed", "chat_id": request_context.user_message.id},
            )
            logger.info("✅ Orchestration completed successfully")

        except asyncio.CancelledError:
            # client disconnected mid-turn (e.g. page refresh) — the finally
            # block below still records what we've got, then this propagates
            # so the task is actually marked cancelled
            logger.warning(
                f"⚠️ Orchestration cancelled (client disconnected): session={request_context.session_id}"
            )
            raise
        except Exception as e:
            logger.exception(f"❌ Unhandled orchestrator error: {e}")
            await sse_stream.send_error(
                "Hmm... something went wrong while processing your query."
            )
        finally:
            if (conversation_orchestrator is not None 
                and conversation_orchestrator.result is not None):
                # shield the recording from cancellation and timeout, but still log if it fails
                # NOTE: this can be a task, with retries to increase the change of success
                # we can make the timeout a task configuration parameter
                try:
                    await asyncio.shield(
                        asyncio.wait_for(
                            record_chat_run(
                                request_context, conversation_orchestrator), 
                            timeout=SAVE_LOG_TIMEOUT
                        )
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"record_chat_run id: {request_context.user_message.id} timed out")

        await sse_stream.close()
