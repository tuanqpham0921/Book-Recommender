import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from app.api.schemas import ChatIn
from app.common.messages import UserMessage
from app.orchestration.orchestrator import Orchestrator
from app.api.dependencies import (
    get_request_context_factory,
    get_orchestrator,
)
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])

async def generate_chat_response(
    orchestrator: Orchestrator,
    request_context: RequestContext,
) -> AsyncGenerator[Any, None]:
    # create_task cannot meaningfully fail here (calling an async def only
    # creates the coroutine; nothing in run() executes yet)
    orchestrator_task = asyncio.create_task(
            orchestrator.run(request_context=request_context)
        )

    try:
        async for event in request_context.sse_stream:
            yield event
            
        await orchestrator_task
    except Exception as e:
        # TODO: review this
        # realistically only the wait_for timeout: SSEStream.__anext__ and
        # Orchestrator.run both swallow their own exceptions.
        # yield the error directly — send_error() would enqueue an event
        # that this generator (the queue's only consumer) no longer reads        
        logger.exception("Orchestration stream failed", exc_info=e)
        yield ServerSentEvent(
            data=json.dumps({"type": "error", "data": "Orchestration error"})
        )
    finally:
        # covers every exit: normal end (no-op), CancelledError (client
        # disconnect), GeneratorExit (aclose) — the task never outlives
        # the stream
        await request_context.sse_stream.close()
        if not orchestrator_task.done():
            orchestrator_task.cancel()
            await asyncio.gather(orchestrator_task, return_exceptions=True)


@router.post("/session/{session_id}/message")
async def chat(
    session_id: str,
    chat_in: ChatIn, # NOTE: this can probably use UserMessage
    orchestrator: Orchestrator = Depends(get_orchestrator),
    request_context_factory: Callable = Depends(get_request_context_factory),
) -> EventSourceResponse:
    """Send a message to a session with SSE response."""
    if not chat_in.message or not chat_in.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    if len(chat_in.message) > 2000:
        raise HTTPException(
            status_code=400,
            detail=f"Message is too long. Maximum {2000} characters allowed.",
        )

    request_context = await request_context_factory(
        session_id, UserMessage(content=chat_in.message)
    )
    logger.info(f"🚀 Starting chat for session: {request_context.session_id}")

    return EventSourceResponse(
        generate_chat_response(
            orchestrator=orchestrator,
            request_context=request_context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
        },
        # Safety net, not the primary close path: EventSourceResponse runs
        # this after its internal task group is fully done, which happens
        # whether that's from normal completion OR the disconnect path
        # (sse_starlette's task group swallows the cancellation it raises
        # internally). sse_stream.close() is idempotent (guards on
        # _closed/_finished), so this just guarantees the stream is never
        # left dangling even if Orchestrator.run's own cleanup got cut off.
        background=BackgroundTask(request_context.sse_stream.close),
    )
