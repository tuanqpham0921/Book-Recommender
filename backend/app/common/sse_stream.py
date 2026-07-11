import asyncio
import json
import logging
import time
from typing import Any

from sse_starlette import ServerSentEvent

logger = logging.getLogger(__name__)

SSE_TIMEOUT = 120 # seconds

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

        # transcript of what was sent, for replay (persisted per turn as
        # chat_runs.sse_events). Consecutive content.delta chars coalesce
        # into _char_buffer instead of one entry per char — the buffer is
        # flushed into events as a single section when a different-typed
        # event arrives, on an explicit flush_chars() (the LLM client calls
        # it after its delta loop, since LLM chunk boundaries aren't
        # deterministic), and on close(). t/t_end are seconds since stream
        # creation so a replay can reproduce the original pacing.
        self._t0 = time.monotonic()
        self.events: list[dict] = []
        self._char_buffer: list[str] = []
        self._char_t_start: float | None = None
        self._char_t_end: float | None = None

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._t0, 3)

    def flush_chars(self) -> None:
        """Close out the current coalesced content.delta section, if any."""
        if not self._char_buffer:
            return
        self.events.append({
            "type": "content.delta",
            "data": "".join(self._char_buffer),
            "t": self._char_t_start,
            "t_end": self._char_t_end,
        })
        self._char_buffer.clear()
        self._char_t_start = None
        self._char_t_end = None

    def _record(self, payload: dict) -> None:
        """Record an outgoing event payload into the transcript."""
        if payload.get("type") == "content.delta" and isinstance(payload.get("data"), str):
            if not self._char_buffer:
                self._char_t_start = self._elapsed()
            self._char_t_end = self._elapsed()
            self._char_buffer.append(payload["data"])
            return
        self.flush_chars()
        self.events.append({**payload, "t": self._elapsed()})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._finished:
            raise StopAsyncIteration
        if self._closed:
            return

        try:
            data = await asyncio.wait_for(self._queue.get(), timeout=SSE_TIMEOUT)
            if data is self._stream_end:
                self._finished = True
                raise StopAsyncIteration
            return ServerSentEvent(data=data)
        except asyncio.CancelledError:
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
        if self._closed or self._finished:
            return
        
        if isinstance(data, dict):
            data = json.dumps(data)
            
        try:
            await self._queue.put(data)
        except Exception as e:
            logger.exception(f"❌ Error putting data into the queue: {data} with type: {type(data)}", exc_info=e)
    
    async def send(self, event_type: str, data: dict[str, Any] | str):
        """Send an SSE event with structured data."""
        # guard here (not just in put) so events dropped after close/timeout
        # never enter the transcript — it should hold only what was delivered
        if self._closed or self._finished:
            return
        payload = {"type": event_type, "data": data}
        self._record(payload)
        await self.put(json.dumps(payload))

    async def send_book_card(self, position: int, data: dict):
        """Send raw JSON data."""
        # TODO: fix this so data={position, data}
        if self._closed or self._finished:
            return
        payload = {"type": "book_card", "position": position, "data": data}
        self._record(payload)
        await self.put(json.dumps(payload))

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
        # even when already closed/finished: trailing chars were enqueued
        # before the stream ended, so they belong in the transcript
        self.flush_chars()
        if self._closed or self._finished:
            return

        self._closed = True
        await self._queue.put(self._stream_end)
        logger.info("🔚 Endpoint cleanup: closing SSE stream")