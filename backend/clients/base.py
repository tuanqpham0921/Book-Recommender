from abc import ABC, abstractmethod
from typing import Any

import asyncio
from pydantic import BaseModel, ConfigDict
from clients.messages import APIMessage, AssistantMessage
from app.common.sse_stream import SSEStream

import logging

logger = logging.getLogger(__name__)


class BaseLLMRequest(BaseModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt: str
    messages: list[APIMessage]
    model: str
    sse_stream: SSEStream | None = None

    @abstractmethod
    def to_payload(self) -> dict[str, Any]: ...

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the request, not its contents.

        `LLMClient.execute` is a `@task`, so this request is what lands in
        `WorkFlowOperationResult.input` on every LLM step — and the full prompt plus
        message list would then sit in every `chat_runs` row, which is exactly
        what `save_payload` exists to gate. Sizes and the model answer the
        questions a trace is actually read for ("which model, how much context,
        which tools were offered"); the payload itself is available on demand.

        Defined here rather than on each provider's request so a new one is
        summarized correctly by default, and worth overriding only for a
        provider whose shape this misses.
        """
        return {
            "model": self.model,
            "prompt_chars": len(self.prompt),
            "num_messages": len(self.messages),
            "streaming": self.sse_stream is not None,
        }


class BaseLLMClient(ABC):
    """Abstract base interface for all LLM providers."""

    client: Any
    max_tokens: int
    semaphore: asyncio.Semaphore

    @abstractmethod
    async def execute(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        """Execute a request (stream or not). Implementations are @task
        decorated, so callers receive an WorkFlowOperationResult envelope whose
        output is the AssistantMessage."""
        ...

    @abstractmethod
    async def close(self):
        """Close any resources used by the client."""
        ...

    @abstractmethod
    def token_count(self, text: str) -> int:
        """Count the number of tokens in the text."""
        ...

    def over_max_tokens(self, token_count: int) -> bool:
        return token_count > self.max_tokens

    @abstractmethod
    async def ping(self) -> bool:
        """Ping the API."""
        ...
