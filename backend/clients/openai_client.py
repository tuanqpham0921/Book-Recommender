import asyncio
import logging
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .base import BaseLLMClient, BaseLLMRequest
from clients.messages import AssistantMessage, TokenUsage
from app.common.sse_stream import SSEStream
from airglider import task
from common.utils import save_file
from config.constants import FilesLocationConstants, OpenAIConstants
from config.settings import OpenAISettings

logger = logging.getLogger(__name__)


class EmbeddingsResult(BaseModel):
    """What one embeddings call produced.

    A model rather than bare vectors so the `@task` envelope can promote
    `token_usage` — the same hook `AssistantMessage` rides — because embedding
    spend used to vanish from the run record entirely.

    `embeddings` is excluded from serialization: ~1KB of floats per text that
    no reader of a `chat_runs` row can use. Callers unwrap and read it live.
    """

    embeddings: list[list[float]] = Field(default_factory=list, exclude=True)
    token_usage: TokenUsage | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"num_texts": len(self.embeddings)}


class OpenAIClient(BaseLLMClient):
    def __init__(self, openai_settings: OpenAISettings):
        """Initialize the OpenAIClient."""
        if not openai_settings.API_KEY:
            raise ValueError("OpenAI API key not set")
        
        self.client               = AsyncOpenAI(api_key=openai_settings.API_KEY)
        self.base_model           = openai_settings.BASE_MODEL
        self.embedding_model      = openai_settings.EMBEDDING_MODEL
        self.embedding_dimensions = openai_settings.EMBEDDING_DIMENSIONS
        self.max_tokens = OpenAIConstants.MAX_TOKENS
        
        self.semaphore = asyncio.Semaphore(openai_settings.MAX_CONCURRENCY)
    
    @task
    async def get_embeddings(self, input: list[str]) -> EmbeddingsResult:
        """Embed `input`. A `@task` like `execute`: the call is its own step in
        the trace, a failure lands on the envelope rather than raising through
        the caller, and the usage is promoted off the returned model."""
        if self.token_count(input) > self.max_tokens:
            raise ValueError(f"Input is too long. Max tokens: {self.max_tokens}")

        async with self.semaphore:
            response = await self.client.embeddings.create(
                input=input,
                model=self.embedding_model,
                dimensions=self.embedding_dimensions,
            )

        return EmbeddingsResult(
            embeddings=[data.embedding for data in response.data],
            # embeddings bill input only, so completion stays 0
            token_usage=TokenUsage(
                model=response.model,
                total=response.usage.total_tokens,
                prompt=response.usage.prompt_tokens,
            ),
        )

    @task
    async def execute(self, req: BaseLLMRequest, save_payload: bool = False) -> AssistantMessage:
        """Execute the chat completion.

        Typed at the base request, matching `BaseLLMClient.execute` — the body
        only ever touches `to_payload()` and `sse_stream`, both of which the
        base declares, and narrowing it here made every app-layer caller (which
        holds a `BaseLLMRequest`) an error.
        """
        payload = req.to_payload()

        async with self.semaphore:
            final_completion = await self._chat_stream(payload, req.sse_stream)
        
        response_message = final_completion.choices[0].message
        assistant_msg = AssistantMessage(
            id=final_completion.id,
            content=response_message.content,
            tool_calls=response_message.tool_calls,
            refusal=response_message.refusal,
            token_usage=self._extract_token_usage(final_completion.usage, payload['model']),
        )
        
        if save_payload:
            payload["id"] = assistant_msg.id
            save_file(payload, 
                  path=FilesLocationConstants.PAYLOAD_DIR, 
                  file_name=f"openai_payload_{payload['id']}")
            
        return assistant_msg
        
    @staticmethod
    def _extract_token_usage(usage, model) -> TokenUsage:
        """Map a CompletionUsage onto TokenUsage. `prompt_tokens_details` and
        its `cached_tokens` are both Optional on the OpenAI side — absent on
        models/endpoints without prompt caching — so default them to 0."""
        if usage is None:
            # zero usage, not "no usage": the model still ran, and an empty
            # TokenUsage sums and strips exactly like one with counts
            return TokenUsage(model=model)

        prompt_details = usage.prompt_tokens_details
        completion_details = usage.completion_tokens_details

        return TokenUsage(
            model = model,
            total=usage.total_tokens,
            prompt=usage.prompt_tokens,
            completion=usage.completion_tokens,
            cached=prompt_details.cached_tokens if prompt_details else 0,
            reasoning_tokens=(
                completion_details.reasoning_tokens
                if completion_details
                else 0
            ),
        )

    async def _chat_stream(self, payload: dict, sse_stream: Optional[SSEStream]):
        """Stream the chat completion."""
        async with self.client.beta.chat.completions.stream(**payload) as stream:
            async for event in stream:
                if event.type == "content.delta" and sse_stream:
                    await sse_stream.send_chars(data=event.delta)

            final_completion = await stream.get_final_completion()
            # print_json(final_completion.model_dump(), "Final Completion")

        return final_completion

    async def close(self):
        """Close the OpenAIClient."""
        await self.client._client.aclose()
        logger.info("OpenAI client closed")

    def token_count(self, text: str | list[str]) -> int:
        import tiktoken
        
        encoding = tiktoken.encoding_for_model(self.embedding_model)
        
        # single string
        if isinstance(text, str):
            return len(encoding.encode(text))
        
        # list of strings
        return sum(len(encoding.encode(item)) for item in text)
    
    @task
    async def ping(self):
        """Ping the OpenAI API."""
        
        response = await self.client.responses.create(
            model=self.base_model,
            input="ping"
        )
        return response
