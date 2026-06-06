import logging
import asyncio
from typing import AsyncGenerator, Any, Callable

from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, HTTPException, Depends

from app.api.schemas import ChatIn
from app.active_streams import ActiveStreamRegistry
from app.common.messages import UserMessage
from app.orchestration.orchestrator import Orchestrator
from app.api.dependencies import (
    get_active_stream_registry,
    get_request_context_factory,
    get_orchestrator,
)
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


async def generate_chat_response(
    orchestrator: Orchestrator,
    request_context: RequestContext,
    registry: ActiveStreamRegistry,
) -> AsyncGenerator[Any, None]:
    
    # make sure to register the stream with the registry
    try:
        orchestrator_task = asyncio.create_task(
            orchestrator.run(request_context=request_context)
        )
        
        # register the stream with the registry
        # TODO: make sure this works with the new registry
        await registry.register(
            request_context.session_id,
            request_context.sse_stream,
            orchestrator_task,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Unable to register stream") from e

    try:
        async for event in request_context.sse_stream:
            yield event
        await orchestrator_task
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Orchestration error") from e
    finally:
        registry.unregister(request_context.session_id, orchestrator_task)


@router.post("/session/{session_id}/message")
async def chat(
    session_id: str,
    chat_in: ChatIn,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    request_context_factory: Callable = Depends(get_request_context_factory),
    registry: ActiveStreamRegistry = Depends(get_active_stream_registry),
) -> EventSourceResponse:
    """Send a message to a session with SSE response."""
    if not chat_in.message or not chat_in.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    if len(chat_in.message) > 2000:
        raise HTTPException(
            status_code=400,
            detail=f"Message is too long. Maximum {2000} characters allowed.",
        )

    
    request_context = request_context_factory(
        session_id, UserMessage(content=chat_in.message)
    )
    logger.info(f"🚀 Starting chat for session: {request_context.session_id}")

    return EventSourceResponse(
        generate_chat_response(
            orchestrator=orchestrator,
            request_context=request_context,
            registry=registry,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
        },
    )


@router.post("/session/{session_id}/stop")
async def stop_stream(
    session_id: str,
    registry: ActiveStreamRegistry = Depends(get_active_stream_registry),
) -> dict[str, str]:
    """Stop the active SSE stream for a session."""
    stopped = await registry.stop(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="No active stream for session")
    return {"message": f"Stream stopped for session {session_id}"}
