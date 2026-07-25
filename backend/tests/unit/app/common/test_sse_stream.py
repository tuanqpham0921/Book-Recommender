"""Tests for app/common/sse_stream.py"""

import asyncio
import json

import pytest

from app.common.sse_stream import SSEStream


async def _collect(stream: SSEStream) -> list:
    return [event async for event in stream]


async def _last_payload(stream: SSEStream) -> dict:
    """Drain the most recently enqueued item and parse it as a JSON payload."""
    raw = stream._queue.get_nowait()
    while not stream._queue.empty():
        raw = stream._queue.get_nowait()
    return json.loads(raw)


class TestSend:
    async def test_send_enqueues_json_payload(self):
        stream = SSEStream()
        await stream.send("ui.loading", "Thinking...")
        raw = await stream._queue.get()
        assert json.loads(raw) == {"type": "ui.loading", "data": "Thinking..."}

    async def test_send_is_noop_after_close(self):
        stream = SSEStream()
        await stream.close()
        await stream._queue.get()  # drain the sentinel close() enqueued
        await stream.send("ui.loading", "too late")
        assert stream._queue.empty()

    async def test_send_chat_id_wraps_in_dict(self):
        stream = SSEStream()
        await stream.send_chat_id("chat_123")
        payload = await _last_payload(stream)
        assert payload["type"] == "chat.id"
        assert payload["data"] == {"chat_id": "chat_123"}

    async def test_send_error(self):
        stream = SSEStream()
        await stream.send_error("boom")
        payload = await _last_payload(stream)
        assert payload["type"] == "error"
        assert payload["data"] == "boom"

    async def test_send_mermaid(self):
        stream = SSEStream()
        await stream.send_mermaid("graph TD; A-->B")
        payload = await _last_payload(stream)
        assert payload["type"] == "mermaid.diagram"
        assert payload["data"] == "graph TD; A-->B"

    async def test_send_noop_when_event_type_empty(self):
        stream = SSEStream()
        await stream.send("", "some data")
        assert stream._queue.empty()

    async def test_send_noop_when_event_type_none(self):
        stream = SSEStream()
        await stream.send(None, "some data")
        assert stream._queue.empty()

    async def test_send_noop_when_data_empty_string(self):
        stream = SSEStream()
        await stream.send("ui.loading", "")
        assert stream._queue.empty()

    async def test_send_noop_when_data_none(self):
        stream = SSEStream()
        await stream.send("ui.loading", None)
        assert stream._queue.empty()

    async def test_send_noop_when_data_empty_dict(self):
        stream = SSEStream()
        await stream.send("ui.loading", {})
        assert stream._queue.empty()


class TestSendBookCard:
    async def test_send_book_card_enqueues_position(self):
        stream = SSEStream()
        await stream.send_book_card(0, {"title": "Dune"})
        payload = await _last_payload(stream)
        assert payload == {
            "type": "book_card",
            "position": 0,
            "data": {"title": "Dune"},
        }

    async def test_send_book_card_is_noop_after_close(self):
        stream = SSEStream()
        await stream.close()
        await stream._queue.get()  # drain the sentinel close() enqueued
        await stream.send_book_card(0, {"title": "Dune"})
        assert stream._queue.empty()

    async def test_send_book_card_noop_when_data_empty_dict(self):
        stream = SSEStream()
        await stream.send_book_card(0, {})
        assert stream._queue.empty()

    async def test_send_book_card_noop_when_data_none(self):
        stream = SSEStream()
        await stream.send_book_card(0, None)
        assert stream._queue.empty()


class TestPut:
    async def test_put_serializes_dict(self):
        stream = SSEStream()
        await stream.put({"a": 1})
        item = await stream._queue.get()
        assert item == json.dumps({"a": 1})

    async def test_put_passes_through_str(self):
        stream = SSEStream()
        await stream.put("raw")
        item = await stream._queue.get()
        assert item == "raw"

    async def test_put_noop_after_closed(self):
        stream = SSEStream()
        await stream.close()
        await stream._queue.get()  # drain the sentinel close() enqueued
        await stream.put("late")
        assert stream._queue.empty()


class TestSendChars:
    async def test_send_chars_enqueues_one_item_per_char(self):
        stream = SSEStream()
        await stream.send_chars("hi", delay=0)
        assert stream._queue.qsize() == 2


class TestClose:
    async def test_close_is_idempotent(self):
        stream = SSEStream()
        await stream.close()
        await stream.close()
        assert stream._closed is True

    async def test_close_enqueues_sentinel(self):
        stream = SSEStream()
        await stream.close()
        item = await stream._queue.get()
        assert item is stream._stream_end


class TestAsyncIteration:
    async def test_iteration_stops_after_close_with_no_pending_events(self):
        stream = SSEStream()
        await stream.close()
        events = await asyncio.wait_for(_collect(stream), timeout=2)
        assert events == []
        assert stream._finished is True

    async def test_iteration_drains_pending_events_then_stops(self):
        stream = SSEStream()
        await stream.send_ui_loading("hi")
        await stream.close()
        events = await asyncio.wait_for(_collect(stream), timeout=2)
        assert len(events) == 1
        assert stream._finished is True

    async def test_anext_after_finished_raises_immediately(self):
        stream = SSEStream()
        await stream.close()
        await _collect(stream)
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_iteration_survives_close_racing_the_consumer(self):
        """Regression test: __anext__ used to `return` (yielding None) as
        soon as self._closed was set, without ever draining the queue. If
        close() ran while the consumer was between __anext__ calls, the
        _stream_end sentinel it enqueued was never read, _finished never
        flipped, and the `async for` loop spun on None forever."""
        stream = SSEStream()
        received = []

        async def consume():
            async for event in stream:
                received.append(event)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)  # let the consumer block inside queue.get()
        await stream.send_chars("hi", delay=0)
        await stream.close()

        await asyncio.wait_for(consumer, timeout=2)
        assert stream._finished is True
        # "hi" is sent char-by-char onto the wire, so the consumer sees 2
        # raw ServerSentEvents
        assert len(received) == 2

    async def test_anext_times_out_and_finishes(self, monkeypatch):
        monkeypatch.setattr("app.common.sse_stream.SSE_TIMEOUT", 0.05)
        stream = SSEStream()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert stream._finished is True

    async def test_anext_cancelled_marks_finished_and_reraises(self):
        stream = SSEStream()
        task = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream._finished is True
