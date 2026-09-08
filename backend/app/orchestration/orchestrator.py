import asyncio
import logging
import time

from app.common.sse_stream import SSEStream
from app.common.request_context import RequestContext

from app.domains.books.external import BookRequestContext
from app.domains.node_input import NodeInput
from app.orchestration.triage import TriageWorkflow
from app.orchestration.task_runner import TaskRunnerInput, TaskRunnerWorkflow
from app.orchestration.run_recorder import record_chat_run
from app.orchestration.write_recommendations import (
    GenerateRecommendationsExecutor,
    RecommendationsInput,
)
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
        triage_workflow: TriageWorkflow | None = None
        task_runner: TaskRunnerWorkflow | None = None
        writer: GenerateRecommendationsExecutor | None = None
        # Root of the turn's trace tree; the workflow envelopes are hung off it
        # in the finally block, so ok/duration/token_usage cover the whole turn.
        record = OperationResult(
            name=f"orchestrator_{request_context.user_message.id}",
        )
        messages: list[APIMessage] = [request_context.user_message]
        time_start = time.perf_counter()
        
        # Core work
        try:
            # First and unconditionally: this id exists before any work
            # starts, so the client can attach feedback even if the turn later
            # errors, times out, or is stopped before 'complete' fires.
            await sse_stream.send_chat_id(request_context.user_message.id)
            await sse_stream.send_ui_loading("Starting conversation...")

            triage_workflow = TriageWorkflow(request_context, messages=messages)
            await asyncio.wait_for(
                triage_workflow(
                    NodeInput(instruction=request_context.user_message.content),
                    # use_caching=False,
                ),
                timeout=CONVERSATION_TIMEOUT,
            )

            # No plan when triage handled the turn without planning (small
            # talk, a refusal, a cache miss on a failed planner): nothing for
            # the runner to execute. A bare read, not `unwrap()` — triage has
            # already told the user what its own failure means.
            plan = triage_workflow.result.parse_result
            if triage_workflow.record.ok and plan and plan.accepted_goals:
                task_runner = TaskRunnerWorkflow(request_context, messages=messages)
                await asyncio.wait_for(
                    # the only place triage and the runner are wired together,
                    # so the runner never learns a triage layer exists
                    task_runner(TaskRunnerInput(plan=plan)),
                    timeout=CONVERSATION_TIMEOUT,
                )
                writer = await self._write_reply(request_context, task_runner, messages)

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
            for workflow in (triage_workflow, task_runner, writer):
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
                        triage_workflow,
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
    async def _write_reply(
        request_context: RequestContext,
        task_runner: TaskRunnerWorkflow,
        messages: list[APIMessage],
    ) -> GenerateRecommendationsExecutor | None:
        """Write the turn's reply from everything the plan produced.

        The third layer of the turn, and the only one that speaks prose. It is
        wired here rather than reached through the registry because it is not a
        capability: no goal targets it, nothing depends on it, and it runs once
        per plan whatever the plan was. That is the same reason `Triage` is a
        workflow in `orchestration/` rather than a node — and it keeps the
        import pointing downward, since `orchestration/` may read `domains/`.

        Returns the workflow so the caller can hang its record on the turn's
        tree, matching how triage and the runner are handled; None when there
        was nothing to write about or nowhere to write from.

        Two ways to decline, both quiet:

        - **No results.** A plan whose every goal was unreachable leaves an
          empty map. There is no evidence to write from, so the stage would
          only invent one — the same failure the `ValueError` in its `run`
          guards against.
        - **No book store on this request.** Narrowing is what a node's
          `NodeSpec.context` did at dispatch; this stage has no spec, so it
          narrows here. A `LookupError` means the services it needs are not on
          this request, which is a deployment problem rather than a turn that
          should die — the cards already streamed, so the user loses the prose
          and nothing else.
        """
        results = list(task_runner.result.task_results.values())
        if not results:
            logger.warning("No task results to write a reply from")
            return None

        try:
            ctx = BookRequestContext.narrow(request_context)
        except LookupError as e:
            logger.warning(f"Skipping the reply: {e}")
            return None

        writer = GenerateRecommendationsExecutor(ctx, messages=messages)
        await asyncio.wait_for(
            writer(RecommendationsInput(results=results)),
            timeout=CONVERSATION_TIMEOUT,
        )
        return writer

    @staticmethod
    async def _finalize(
        request_context: RequestContext,
        record: OperationResult,
        triage_workflow: TriageWorkflow | None,
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
                    triage_workflow,
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
