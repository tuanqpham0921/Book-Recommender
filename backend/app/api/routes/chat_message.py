import logging
import asyncio
from typing import AsyncGenerator, Any, Callable

from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, HTTPException, Depends

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
    try:
        orchestrator_task = asyncio.create_task(
            orchestrator.run(request_context=request_context)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Unable to register stream") from e

    try:
        async for event in request_context.sse_stream:
            yield event
        
        await asyncio.wait_for(orchestrator_task, timeout=300.0)
        
    except Exception as e:
        # TODO: cancel the task if things failed
        raise HTTPException(status_code=500, detail="Orchestration error") from e


@router.post("/session/{session_id}/message")
async def chat(
    session_id: str,
    chat_in: ChatIn,
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

    
    request_context = request_context_factory(
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
    )