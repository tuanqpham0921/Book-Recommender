from typing import Any, TypeVar

from common.operation import OperationResult
from common.workflow import Workflow
from app.common.messages import BaseMessage
from app.common.sse_stream import SSEStream
from clients.base import BaseLLMClient

OutputT = TypeVar("OutputT")


class UserFacingBaseWorkflow(Workflow[OutputT]):
    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
    ):
        super().__init__(output_type)
        self.llm_client = llm_client
        self.sse_stream = sse_stream

    async def generate_user_response(
        self, messages: list[BaseMessage], prompt: str
    ) -> OperationResult[Any]:
        from clients.openai_requests import OpenAIChatRequest

        req = OpenAIChatRequest(
            prompt=prompt,
            messages=messages,
            sse_stream=self.sse_stream,
            temperature=0.7,
            top_p=1.0,
        )
        return await self.run_async_step(self.llm_client.execute(req))
