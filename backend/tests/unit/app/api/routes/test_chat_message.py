import asyncio
from types import SimpleNamespace

import pytest

from app.api.routes.chat_message import generate_chat_response


class _FakeSSEStream:
    def __init__(self, error=None):
        self.error = error
        self.sent_error = None
        self.iterated = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.iterated:
            raise StopAsyncIteration
        self.iterated = True
        if self.error is not None:
            raise self.error
        return {"event": "ping"}

    async def send_error(self, text: str):
        self.sent_error = text


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
async def test_generate_chat_response_emits_error_and_cancels_on_stream_failure():
    orchestrator = _FakeOrchestrator()
    request_context = SimpleNamespace(
        sse_stream=_FakeSSEStream(error=RuntimeError("boom"))
    )

    events = [
        event async for event in generate_chat_response(orchestrator, request_context)
    ]

    assert events == []
    assert orchestrator.started is True
    assert orchestrator.cancelled is True
    assert request_context.sse_stream.sent_error == "Orchestration error"
