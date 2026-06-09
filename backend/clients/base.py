from abc import ABC, abstractmethod
from typing import Any

import asyncio
from dataclasses import dataclass
from app.common.messages import APIMessage, SystemMessage
from app.common.sse_stream import SSEStream
from config import settings

@dataclass
class BaseLLMRequest(ABC):
    """Base schema for any LLM request (OpenAI, Anthropic, etc.)."""
    model: str
    prompt: str
    messages: list[APIMessage]
    tool_models: list[type]

    @abstractmethod
    def to_payload(self) -> dict[str, Any]:
        """Convert this request to provider-specific API payload."""
        ...
        


class BaseLLMClient(ABC):
    """Abstract base interface for all LLM providers."""

    client: Any
    max_tokens: int
    semaphore: asyncio.Semaphore

    @abstractmethod
    async def execute(self, req: BaseLLMRequest):
        """Execute a request (stream or not) and return an AssistantMessage."""
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