import logging
import asyncio
from typing import AsyncGenerator, Any, Callable

from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, HTTPException, Depends

from app.api.schemas import ChatIn
from app.common.messages import UserMessage
from app.orchestration.orchestrator import Orchestrator
from app.api.dependencies import get_request_context_factory, get_orchestrator
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)

# Store assistant instances to access book results
router = APIRouter(tags=["Chat"])

async def generate_chat_response(
    orchestrator: Orchestrator,
    request_context: RequestContext,
) -> AsyncGenerator[Any, None]:

    try:
        # Start orchestrator in background task
        orchestrator_task = asyncio.create_task(
            orchestrator.run(request_context=request_context)
        )

        # Stream events as they come
        async for event in request_context.sse_stream:
            yield event

        # Wait for orchestrator to complete
        await orchestrator_task

    except Exception as e:
        logger.exception(f"❌ Orchestration error at endpoint: {e}")
        if request_context.app_env == "DEVELOPMENT":
            await request_context.sse_stream.send_error(f"❌ Endpoint orchestration error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
        elif request_context.app_env == "PRODUCTION":
            await request_context.sse_stream.send_error(
                "Something went wrong while processing your request."
            )
            
            
    finally:
        
        await request_context.sse_stream.close()

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
    
    # enforce message length limit
    if len(chat_in.message) > 2000:
        raise HTTPException(
            status_code=400, 
            detail=f"Message is too long. Maximum {2000} characters allowed."
        )
        
    # make the request context
    request_context = request_context_factory(session_id, UserMessage(content=chat_in.message))
    logger.info(f"🚀 Starting chat for session: {request_context.session_id}")
    
    # start the chat response
    return EventSourceResponse(
        generate_chat_response(
            orchestrator=orchestrator,
            request_context=request_context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # "Connection": "keep-alive",
        }
    )