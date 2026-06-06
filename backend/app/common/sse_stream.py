import json
import asyncio
import logging
from typing import Dict, Any, Optional

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
            logger.exception(
                f"❌ SSE stream error: {e}"
            )  # Use exception() for full traceback
            raise StopAsyncIteration

    async def send(self, type: str = "content.delta", data: str = ""):
        """Send a typed message."""
        if self._finished:
            logger.warning("🔚 SSE stream already finished")
            return
        
        try:
            await self._queue.put(json.dumps({"type": type, "data": data}))
        except Exception as e:
            logger.exception(f"❌ Error sending SSE type: {type} with data: {data}")
            
    async def send_event(self, event_type: str, data: Dict[str, Any]):
        """Send an SSE event with structured data."""
        
        try:
            event_data = {"event": event_type, "data": json.dumps(data)}
            await self._queue.put(json.dumps(event_data))
            logger.debug(f"📡 SSE Event sent: {event_type}")
        except Exception as e:
            logger.exception(f"❌ Error sending SSE event: {event_type} with data: {data}")
            
    async def send_book_card(self, position: int, data: dict):
        """Send raw JSON data."""
        if self._finished:
            logger.warning("🔚 SSE stream already finished")
            return
        
        try:
            if not self._finished:
                await self._queue.put(json.dumps({"type": "book_card", "position": position, "data": data}))
                await asyncio.sleep(0.2)  # Smooth streaming
        except Exception as e:
            logger.exception(f"❌ Error sending book card: {position} with data: {data}")

    async def send_chars(self, data: str, delay: float = 0.01):
        """Stream text character by character for smoother effect."""
        if not self._finished:
            for ch in data:
                await self.send(data=str(ch))
                await asyncio.sleep(delay)

    async def send_ui_loading(self, text: str):
        """Send loading message to UI."""
        await self.send(type="ui.loading", data=text)

    async def send_error(self, text: str):
        """Send error message."""
        await self.send(type="error", data=text)

    async def send_step_complete(self, step: str, result: Optional[Dict] = None):
        """Send step completion notification."""
        data = {"step": step}
        if result:
            data["result"] = result
        await self.send(type="step.complete", data=json.dumps(data))

    async def send_divider(self, data: str = "\n\n---\n\n"):
        """Send divider."""
        await self.send(data=data)

    async def send_mermaid(self, data: str):
        """Send mermaid diagram."""
        await self.send(type="mermaid.diagram", data=data)
    
    async def close(self):
        """Close the stream."""
        if not self._finished:
            self._finished = True
            await self._queue.put(self._stream_end)
            logger.info("🔚 Endpoint cleanup: closing SSE stream")