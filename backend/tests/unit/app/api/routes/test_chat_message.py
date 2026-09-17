import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.api.routes.chat_message import generate_chat_response

logger = logging.getLogger(__name__)

# TODO: review this
class _FakeSSEStream:
    def __init__(self, error=None):
        self.error = error
        self.sent_error = None
        self.iterated = False
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        # the real SSEStream always suspends on queue.get() — model that,
        # otherwise the orchestrator task never gets a tick to start
        await asyncio.sleep(0)
        if self.iterated:
            raise StopAsyncIteration
        self.iterated = True
        if self.error is not None:
            raise self.error
        return {"event": "ping"}

    async def send_error(self, text: str):
        self.sent_error = text

    async def close(self):
        self.closed = True
        logger.info("sse stream closed")

class _FakeOrchestrator:
    def __init__(self):
        self.started = False
        self.cancelled = False

    async def run(self, request_context):
        self.started = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_generate_chat_response_emits_error_and_cancels_on_stream_failure(caplog):
    orchestrator = _FakeOrchestrator()
    request_context = SimpleNamespace(
        sse_stream=_FakeSSEStream(error=RuntimeError("boom"))
    )

    with caplog.at_level(logging.INFO, logger=__name__):
        events = [
            event async for event in generate_chat_response(orchestrator, request_context)
        ]

    # the error must be YIELDED to the client, not send_error()'d into the
    # queue — this generator is the queue's only consumer and has stopped
    assert len(events) == 1
    payload = json.loads(events[0].data)
    assert payload["type"] == "error"
    assert payload["data"] == "Orchestration error"
    assert request_context.sse_stream.sent_error is None

    assert orchestrator.started is True
    assert orchestrator.cancelled is True

    # the finally block must close the stream even on the error path
    assert request_context.sse_stream.closed is True
    assert "sse stream closed" in caplog.text
