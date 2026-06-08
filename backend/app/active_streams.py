import asyncio
import logging
from dataclasses import dataclass

from app.common.sse_stream import SSEStream

logger = logging.getLogger(__name__)


@dataclass
class ActiveChat:
    sse_stream: SSEStream
    task: asyncio.Task

# TODO: move this to Redis or shared memory for instance-level state
class ActiveStreamRegistry:
    """Tracks in-flight chat SSE streams so /stop can cancel the right one."""

    def __init__(self) -> None:
        self._active: dict[str, ActiveChat] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, session_chat_id: str, sse_stream: SSEStream, task: asyncio.Task
    ) -> None:
        async with self._lock:
            existing = self._active.get(session_chat_id)
            if existing is not None and not existing.task.done():
                logger.info("Replacing active stream for session %s", session_chat_id)
                existing.task.cancel()
                await existing.sse_stream.close()
            self._active[session_chat_id] = ActiveChat(sse_stream=sse_stream, task=task)

    def unregister(self, session_id: str, task: asyncio.Task) -> None:
        active = self._active.get(session_id)
        if active is not None and active.task is task:
            self._active.pop(session_id, None)

    async def stop(self, session_chat_id: str) -> bool:
        async with self._lock:
            active = self._active.get(session_chat_id)
            if active is None or active.task.done():
                return False

            logger.info("Stopping active stream for session %s", session_chat_id)
            active.task.cancel()
            await active.sse_stream.close()
            return True
