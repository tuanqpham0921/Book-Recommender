import time
import logging

from openai import AsyncOpenAI
from typing import List, Optional

from .schemas import OpenAIRequest
from .base import BaseLLMClient

from config.settings import OpenAISettings
from app.common.messages import AssistantMessage
from app.common.sse_stream import SSEStream
from config.constants import OpenAIConstants
import asyncio
logger = logging.getLogger(__name__)
from common.operation import task, OperationResult

class OpenAIClient(BaseLLMClient):
    def __init__(self, openai_settings: OpenAISettings):
        """Initialize the OpenAIClient."""
        if not openai_settings.API_KEY:
            raise ValueError("OpenAI API key not set")
        
        self.client               = AsyncOpenAI(api_key=openai_settings.API_KEY)
        self.embedding_model      = openai_settings.EMBEDDING_MODEL
        self.embedding_dimensions = openai_settings.EMBEDDING_DIMENSIONS
        self.max_tokens = OpenAIConstants.MAX_TOKENS
        
        self.semaphore = asyncio.Semaphore(openai_settings.MAX_CONCURRENCY)
    
    # these functions are like session commit()
    # use them similarly to ensure proper error handling and logging
    async def get_embeddings(self, input: list[str]) -> list[list[float]]:
        """Get the embeddings for the input texts."""
        if self.token_count(input) > self.max_tokens:
            raise ValueError(f"Input is too long. Max tokens: {self.max_tokens}")
        
        try:
            async with self.semaphore:
                response = await self.client.embeddings.create(
                                    input=input, 
                                    model=self.embedding_model, 
                                    dimensions=self.embedding_dimensions
                                )
                
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.exception(f"❌❌❌ OpenAI embedding API call failed: {e}")
            raise
        
    async def execute(self, req: OpenAIRequest) -> AssistantMessage:
        # --- Preflight ---
        try:
            payload = req.to_payload()

            start = time.monotonic()
            final_completion = await self._chat_stream(payload, req.sse_stream)
            elapsed = round(time.monotonic() - start, 2)

            response_message = final_completion.choices[0].message
            assistant_msg = AssistantMessage(
                id=final_completion.id,
                content=response_message.content,
                tool_calls=response_message.tool_calls,
                refusal=response_message.refusal,
                elapsed=elapsed,
            )

            # --- Execute ---
            return assistant_msg
        except Exception as e:
            logger.error(f"❌❌❌ OpenAI API call failed: {e}")
            raise e
    
    @task
    async def execute_new(self, req: OpenAIRequest) -> OperationResult:
        """Execute the chat completion."""
        #TODO: add semaphore to the execute method
        
        payload = req.to_payload()

        final_completion = await self._chat_stream(payload, req.sse_stream)

        response_message = final_completion.choices[0].message
        assistant_msg = AssistantMessage(
            id=final_completion.id,
            content=response_message.content,
            tool_calls=response_message.tool_calls,
            refusal=response_message.refusal,
            elapsed=0.0,
        )

        # --- Execute ---
        return OperationResult(
            name="execute",
            ok=True,
            message="OpenAI API call completed successfully",
            result=assistant_msg,
            # details={"payload": payload}
        )


    async def _chat_stream(self, payload: dict, sse_stream: Optional[SSEStream]):
        """Stream the chat completion."""
        async with self.client.beta.chat.completions.stream(**payload) as stream:
            async for event in stream:
                if event.type == "content.delta" and sse_stream:
                    await sse_stream.send_chars(data=event.delta)

            final_completion = await stream.get_final_completion()
            # print_json(final_completion.model_dump(), "Final Completion")

        # one section is done
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
    
    async def ping(self):
        """Ping the OpenAI API."""
        try:
            response = await self.client.responses.create(
                model="gpt-5-nano",
                input="ping"
            )
        except Exception as e:
            logger.exception(f"❌❌❌ OpenAI API ping failed: {e}")
            raise