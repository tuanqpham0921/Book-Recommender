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
        # _closed: producer is done sending (guards re-entrant close()/put()).
        # _finished: consumer has actually drained the end sentinel — only
        # this should stop __anext__, otherwise items still sitting in the
        # queue when close() fires get silently dropped.
        self._closed = False
        self._finished = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._finished:
            raise StopAsyncIteration
        if self._closed:
            return

        try:
            data = await self._queue.get()
            if data is self._stream_end:
                self._finished = True
                raise StopAsyncIteration
            return ServerSentEvent(data=data)
        except asyncio.CancelledError:
            logger.error("⏰ SSE stream CancelledError: client disconnected")
            self._finished = True
            raise
        except asyncio.TimeoutError:
            logger.error("⏰ SSE stream timeout")
            self._finished = True
            raise StopAsyncIteration
        except StopAsyncIteration:
            raise
        except Exception as e:
            logger.exception(f"❌ SSE stream error: {e}")
            self._finished = True
            raise StopAsyncIteration

    async def put(self, data: str | dict):
        """Put data into the queue."""
        if self._closed:
            return
        
        if isinstance(data, dict):
            data = json.dumps(data)
            
        try:
            await self._queue.put(data)
        except Exception as e:
            logger.exception(f"❌ Error putting data into the queue: {data} with type: {type(data)}", exc_info=e)
    
    async def send(self, event_type: str, data: dict[str, Any] | str):
        """Send an SSE event with structured data."""
        await self.put(json.dumps({"type": event_type, "data": data}))
       
    async def send_book_card(self, position: int, data: dict):
        """Send raw JSON data."""
        # TODO: fix this so data={position, data}
        await self.put(json.dumps({"type": "book_card", "position": position, "data": data}))

    async def send_chars(self, data: str, delay: float = 0.01):
        """Stream text character by character for smoother effect."""
        for ch in data:
            await self.send(event_type="content.delta", data=str(ch))
            await asyncio.sleep(delay)

    async def send_ui_loading(self, text: str):
        """Send loading message to UI."""
        await self.send(event_type="ui.loading", data=text)

    async def send_chat_id(self, chat_id: str):
        """Send the chat_id as soon as it's known, so the client can attach
        feedback to this run even if the turn later errors, times out, or
        is stopped before the final 'complete' event is reached."""
        await self.send(event_type="chat.id", data={"chat_id": chat_id})

    async def send_error(self, text: str):
        """Send error message."""
        await self.send(event_type="error", data=text)

    async def send_divider(self, data: str = "\n\n---\n\n"):
        """Send divider."""
        await self.send(event_type="content.delta", data=data)

    async def send_mermaid(self, data: str):
        """Send mermaid diagram."""
        await self.send(event_type="mermaid.diagram", data=data)
    
    async def close(self):
        """Close the stream."""
        if self._closed:
            return

        self._closed = True
        await self._queue.put(self._stream_end)
        logger.info("🔚 Endpoint cleanup: closing SSE stream")