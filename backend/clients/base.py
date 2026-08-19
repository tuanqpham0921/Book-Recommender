from abc import ABC, abstractmethod
from typing import Any, Optional

import asyncio
from pydantic import BaseModel, ConfigDict, Field
from clients.messages import APIMessage, AssistantMessage
from app.common.sse_stream import SSEStream

import logging

logger = logging.getLogger(__name__)


class BaseLLMRequest(BaseModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt: str
    messages: list[APIMessage]
    model: str
    
    # TODO: remove this / streaming=True have the client stream them back
    # and in the workflow I think you can do something like
    # for event in self.llm.execute(req):
    #     if some event: self.sse_stream.put(...)
    #
    # and in the execute
    # you do yield if streaming=true
    # This is the one remaining app import in clients/ — the @task half of
    # separating clients from the app is already done (see BaseLLMClient).
    sse_stream: Optional[SSEStream] = Field(default=None, exclude=True)

    @abstractmethod
    def to_payload(self) -> dict[str, Any]: ...

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the request, not its contents.

        The app wraps every client call in a `@task`
        (`AppWorkflow.llm_execute`), which stamps its arguments — so this is
        what lands in `OperationResult.input` on every LLM step. Without it the
        full prompt and message list would sit in every `chat_runs` row, which
        is what `save_payload` exists to gate. Sizes and the model answer what
        a trace is read for; the payload is available on demand.

        Here rather than on each provider's request, so a new one is summarized
        correctly by default.
        """
        return {
            "model": self.model,
            "prompt_chars": len(self.prompt),
            "num_messages": len(self.messages),
            "streaming": self.sse_stream is not None,
        }


class BaseLLMClient(ABC):
    """Abstract base interface for all LLM providers.

    **Tracing-free by design.** No `@task` anywhere in clients/: a client
    method does its I/O and returns its payload, raising on failure like any
    plain function. The step envelope, the failure capture and the token-usage
    promotion all happen one layer up, on `AppWorkflow`'s thin wrappers
    (`llm_execute`, `get_embeddings`) — the app decides what is a step, the
    client doesn't know envelopes exist. The one airglider import left in this
    package is the `TokenUsage` data shape (see messages.py); airglider is
    itself standalone, so clients stay extractable with it.
    """

    client: Any
    max_tokens: int
    semaphore: asyncio.Semaphore

    @abstractmethod
    async def execute(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        """Execute a request (stream or not) and return the message itself.
        Failures raise; the app's wrapper task is what turns one into a
        recorded step failure."""
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
