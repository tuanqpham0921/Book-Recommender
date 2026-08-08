import asyncio
import logging
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext

from app.domains.planner import PlannerWorkflow
from app.domains.task_runner import TaskRunnerWorkflow
from app.orchestration.run_recorder import record_chat_run
from airglider.task import OperationResult, RuntimeErrorInfo

logger = logging.getLogger(__name__)

SAVE_LOG_TIMEOUT = 60  # seconds
CLOSE_SSE_STREAM_TIMEOUT = 10  # seconds
CONVERSATION_TIMEOUT = 120  # seconds


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
        # PlannerWorkflow mutates its own .record in place and
        # re-raises on cancellation rather than returning it
        conversation_orchestrator = None
        task_runner = None
        # Root of the turn's trace tree. The two workflow envelopes are hung
        # off it in the finally block (one place, so a timed-out or cancelled
        # turn still records what ran), which is what makes ok/duration/
        # token_usage cover the whole turn instead of the planner alone.
        # Bound before the try for the same reason as the two above.
        record = OperationResult(
            name=f"orchestrator_{request_context.user_message.id}",
        )
        time_start = time.perf_counter()
        try:
            # Sent first and unconditionally — this id is generated when the
            # user message is parsed (before any work starts), so the client
            # can attach feedback to this run even if the turn later errors,
            # times out, or is stopped before the 'complete' event fires.
            await sse_stream.send_chat_id(request_context.user_message.id)
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            conversation_orchestrator = PlannerWorkflow(
                sse_stream,
                request_context.user_message,
                request_context.llm_client,
                app_env=request_context.app_env,
            )
            await asyncio.wait_for(
                conversation_orchestrator(request_context=request_context),
                timeout=CONVERSATION_TIMEOUT,
            )

            planner_result = conversation_orchestrator.result.parse_result
            if (
                conversation_orchestrator.record.ok
                and planner_result
                and planner_result.accepted_goals
            ):
                task_runner = TaskRunnerWorkflow(
                    sse_stream,
                    request_context.llm_client,
                    app_env=request_context.app_env,
                )
                await asyncio.wait_for(
                    task_runner(
                        request_context=request_context,
                        planner_result=conversation_orchestrator.result,
                    ),
                    timeout=CONVERSATION_TIMEOUT,
                )

            # Normal completion — chat_id lets the client attach feedback
            # to the chat_runs row recorded in the finally block below
            await sse_stream.send(
                "complete",
                {"status": "completed", "chat_id": request_context.user_message.id},
            )
            # close the sse_stream
            await sse_stream.close()
            logger.info("✅ Orchestration completed successfully")

        except asyncio.CancelledError as e:
            # client disconnected mid-turn (e.g. page refresh) — the finally
            # block below still records what we've got, then this propagates
            # so the task is actually marked cancelled
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
            # Hung here rather than after each await so the timeout/cancel
            # paths above record their partial work too: each workflow mutates
            # its own .record in place, so the envelope is populated whether or
            # not its await returned. isinstance-guarded rather than trusting
            # add_step to validate — a raise inside this finally would replace
            # whatever exception is already in flight and skip the recording
            # and stream close below.
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

            # One shielded unit, not two: a second cancellation landing on
            # *this* task (see EventSourceResponse's disconnect handling —
            # it keeps re-cancelling every checkpoint, and asyncio.gather()
            # re-cancels orchestrator_task when its own await is cancelled)
            # would otherwise raise CancelledError past `except Exception`
            # (CancelledError is a BaseException, not an Exception, since
            # 3.8) mid-way through cleanup, skipping sse_stream.close().
            # Shielding the whole sequence as one background task means that
            # even if this await is cancelled again, close() still runs —
            # we just stop waiting for it here.
            try:
                await asyncio.shield(
                    self._finalize(
                        request_context,
                        record,
                        conversation_orchestrator,
                        task_runner,
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
        conversation_orchestrator: PlannerWorkflow | None,
        task_runner: TaskRunnerWorkflow | None,
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
