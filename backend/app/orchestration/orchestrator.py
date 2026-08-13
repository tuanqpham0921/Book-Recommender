import asyncio
import logging
import time

from app.common.sse_stream import SSEStream
from app.common.request_context import RequestContext

from app.domains.node_input import NodeInput
from app.orchestration.triage import TriageWorkflow
from app.orchestration.task_runner import TaskRunnerInput, TaskRunnerWorkflow
from app.orchestration.run_recorder import record_chat_run
from airglider import OperationResult, RuntimeErrorInfo

from clients.messages import (
    APIMessage,
)

logger = logging.getLogger(__name__)

SAVE_LOG_TIMEOUT = 60  # seconds
CLOSE_SSE_STREAM_TIMEOUT = 10  # seconds
CONVERSATION_TIMEOUT = 120  # seconds


class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        pass

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""

        sse_stream = request_context.sse_stream
        # Bound before the try so a cancellation mid-await still leaves them
        # for the finally block — each workflow mutates its own .record in
        # place and re-raises rather than returning it.
        conversation_orchestrator = None
        task_runner = None
        # Root of the turn's trace tree; the workflow envelopes are hung off it
        # in the finally block, so ok/duration/token_usage cover the whole turn.
        record = OperationResult(
            name=f"orchestrator_{request_context.user_message.id}",
        )
        messages: list[APIMessage] = [request_context.user_message]
        time_start = time.perf_counter()
        try:
            # First and unconditionally: this id exists before any work
            # starts, so the client can attach feedback even if the turn later
            # errors, times out, or is stopped before 'complete' fires.
            await sse_stream.send_chat_id(request_context.user_message.id)
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            conversation_orchestrator = TriageWorkflow(
                request_context, messages=messages
            )
            await asyncio.wait_for(
                conversation_orchestrator(
                    NodeInput(query=request_context.user_message.content),
                    # use_caching=False,
                ),
                timeout=CONVERSATION_TIMEOUT,
            )

            planner_result = conversation_orchestrator.result.parse_result
            if (
                conversation_orchestrator.record.ok
                and planner_result
                and planner_result.accepted_goals
            ):
                task_runner = TaskRunnerWorkflow(request_context, messages=messages)
                await asyncio.wait_for(
                    # the only place triage and the runner are wired together,
                    # so the runner never learns a triage layer exists
                    task_runner(TaskRunnerInput(plan=planner_result)),
                    timeout=CONVERSATION_TIMEOUT,
                )

            # chat_id lets the client attach feedback to the chat_runs row
            await sse_stream.send(
                "complete",
                {"status": "completed", "chat_id": request_context.user_message.id},
            )
            await sse_stream.close()
            logger.info("✅ Orchestration completed successfully")

        except asyncio.CancelledError as e:
            # client disconnected mid-turn — the finally block still records
            # what we have, then this propagates so the task is really cancelled
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            logger.warning(
                f"⚠️ Orchestration cancelled: chat_id={request_context.user_message.id}"
            )
            raise
        except TimeoutError as e:
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            record.add_details("Orchestration Task timed out")
            logger.warning(
                f"⚠️ Orchestration timed out: chat_id={request_context.user_message.id}"
            )
            await sse_stream.send_error("The request took too long to process.")
        except Exception as e:
            record.runtime_error = RuntimeErrorInfo.from_exception(e)
            logger.exception(f"❌ Unhandled orchestrator error: {e}")
            await sse_stream.send_error(
                "Hmm... something went wrong while processing your query."
            )
        finally:
            # Here rather than after each await, so the timeout/cancel paths
            # record their partial work too. isinstance-guarded rather than
            # letting add_step raise: a raise in this finally would replace the
            # exception in flight and skip the recording and stream close below.
            for workflow in (conversation_orchestrator, task_runner):
                step = getattr(workflow, "record", None)
                if isinstance(step, OperationResult):
                    record.add_step(step)
            record.ok = (
                record.runtime_error is None
                and bool(record.steps)
                and all(step.ok for step in record.steps)
            )
            record.timing.duration = round(time.perf_counter() - time_start, 2)

            # One shielded unit, not two. A second cancellation landing on this
            # task (EventSourceResponse re-cancels every checkpoint on
            # disconnect) is a BaseException, so it would fly past
            # `except Exception` mid-cleanup and skip sse_stream.close().
            # Shielding the whole sequence means close() still runs — we just
            # stop waiting for it here.
            try:
                await asyncio.shield(
                    self._finalize(
                        request_context,
                        record,
                        conversation_orchestrator,
                        task_runner,
                        messages,
                        sse_stream,
                    )
                )
            except asyncio.CancelledError:
                logger.warning(
                    f"cleanup cancelled for chat_id={request_context.user_message.id}, "
                    "continuing in the background"
                )

    @staticmethod
    async def _finalize(
        request_context: RequestContext,
        record: OperationResult,
        conversation_orchestrator: TriageWorkflow | None,
        task_runner: TaskRunnerWorkflow | None,
        messages: list[APIMessage] | None,
        sse_stream: SSEStream,
    ) -> None:
        """Record the run, then close the stream. Best-effort — never lets a
        slow/failing step here take down the other, or the caller."""
        try:
            await asyncio.wait_for(
                record_chat_run(
                    request_context,
                    record,
                    conversation_orchestrator,
                    task_runner,
                    messages,
                ),
                timeout=SAVE_LOG_TIMEOUT,
            )
        except Exception:
            logger.warning(
                f"record_chat_run id: {request_context.user_message.id} timed out"
            )

        try:
            await asyncio.wait_for(sse_stream.close(), timeout=CLOSE_SSE_STREAM_TIMEOUT)
        except Exception:
            logger.warning(
                f"sse_stream.close() id: {request_context.user_message.id} timed out"
            )
