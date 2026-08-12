import asyncio
import logging
import time

from app.common.sse_stream import SSEStream
from app.common.request_context import RequestContext

from app.domains.node_input import NodeInput
from app.orchestration.triage import TriageWorkflow
from app.orchestration.task_runner import TaskRunnerInput, TaskRunnerWorkflow
from app.orchestration.run_recorder import record_chat_run
from airglider import OperationResult, OperationResult, RuntimeErrorInfo

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
        """Initialize the orchestrator."""
        pass

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""

        sse_stream = request_context.sse_stream
        # created (not just returned from a helper) so that a cancellation
        # mid-await below still leaves this bound for the finally block —
        # TriageWorkflow mutates its own .record in place and
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
        messages: list[APIMessage] = [request_context.user_message]
        time_start = time.perf_counter()
        try:
            # Sent first and unconditionally — this id is generated when the
            # user message is parsed (before any work starts), so the client
            # can attach feedback to this run even if the turn later errors,
            # times out, or is stopped before the 'complete' event fires.
            await sse_stream.send_chat_id(request_context.user_message.id)
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            conversation_orchestrator = TriageWorkflow(
                request_context, messages=messages
            )
            await asyncio.wait_for(
                conversation_orchestrator(
                    NodeInput(query=request_context.user_message.content),
                    use_caching=False,
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
                    # The plan is passed as the runner's declared input, so the
                    # runner never has to know a triage layer produced it —
                    # this is the only place the two are wired together.
                    task_runner(TaskRunnerInput(plan=planner_result)),
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
