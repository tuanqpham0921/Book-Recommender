import asyncio
import json
import logging
from typing import Any

from sse_starlette import ServerSentEvent

logger = logging.getLogger(__name__)


class SSEStream:
    def __init__(self) -> None:
        self._queue = asyncio.Queue()
        self._stream_end = object()
        self._finished = False
        self._timeout = 300.0  # 5 minutes

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._finished:
            raise StopAsyncIteration

        try:
            data = await asyncio.wait_for(self._queue.get(), timeout=self._timeout)
            if data is self._stream_end:
                raise StopAsyncIteration
            return ServerSentEvent(data=data)
        except asyncio.TimeoutError:
            logger.error("⏰ SSE stream timeout")
            # Don't call send_error here to avoid recursion
            raise StopAsyncIteration
        except Exception as e:
            logger.exception(f"❌ SSE stream error: {e}")
            raise StopAsyncIteration

    async def put(self, data: str | dict):
        """Put data into the queue."""
        if self._finished:
            return
        
        if isinstance(data, dict):
            data = json.dumps(data)
            
        try:
            await self._queue.put(data)
        except Exception as e:
            logger.exception(f"❌ Error putting data into the queue: {data} with type: {type(data)}", exc_info=e)
    
    async def send(self, type: str, data: dict[str, Any] | str):
        """Send an SSE event with structured data."""
        await self.put(json.dumps({"type": type, "data": data}))
       
    async def send_book_card(self, position: int, data: dict):
        """Send raw JSON data."""
        # TODO: fix this so data={position, data}
        await self.put(json.dumps({"type": "book_card", "position": position, "data": data}))

    async def send_chars(self, data: str, delay: float = 0.01):
        """Stream text character by character for smoother effect."""
        for ch in data:
            await self.send(type="content.delta", data=str(ch))
            await asyncio.sleep(delay)

    async def send_ui_loading(self, text: str):
        """Send loading message to UI."""
        await self.send(type="ui.loading", data=text)

    async def send_error(self, text: str):
        """Send error message."""
        await self.send(type="error", data=text)

    async def send_divider(self, data: str = "\n\n---\n\n"):
        """Send divider."""
        await self.send(type="content.delta", data=data)

    async def send_mermaid(self, data: str):
        """Send mermaid diagram."""
        await self.send(type="mermaid.diagram", data=data)
    
    async def close(self):
        """Close the stream."""
        if self._finished:
            return
        
        self._finished = True
        await self._queue.put(self._stream_end)
        logger.info("🔚 Endpoint cleanup: closing SSE stream")