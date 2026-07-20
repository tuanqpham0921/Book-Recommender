import logging
from typing import Any

from .base import BaseLLMRequest

from config import settings
from app.common.messages import AssistantMessage, SystemMessage, ToolMessage
from openai import pydantic_function_tool
from openai.types.chat import ChatCompletionFunctionToolParam
from pydantic import model_validator, Field
from typing import Annotated

logger = logging.getLogger(__name__)

MAX_COMPLETION_TOKENS = 1000
TEMPERATURE = 0.3
TOP_P = 0.8
SEED = 42


class OpenAIBaseRequest(BaseLLMRequest):
    model: str = settings.openai.BASE_MODEL
    temperature: float = TEMPERATURE
    top_p: float = TOP_P
    seed: int = SEED
    reasoning_effort: str = 'low'

    @model_validator(mode="after")
    def check_tool_message_linkage(self) -> "OpenAIBaseRequest":
        assistant_tool_call_ids = {
            tc.id
            for m in self.messages
            if isinstance(m, AssistantMessage) and m.tool_calls
            for tc in m.tool_calls
        }
        tool_message_ids = {
            m.tool_call_id for m in self.messages if isinstance(m, ToolMessage)
        }

        orphaned = tool_message_ids - assistant_tool_call_ids
        if orphaned:
            raise ValueError(f"ToolMessage has no matching assistant tool_call: {orphaned}")

        unanswered = assistant_tool_call_ids - tool_message_ids
        if unanswered:
            raise ValueError(f"Assistant tool_call has no ToolMessage reply: {unanswered}")

        return self

    def to_messages_payload(self) -> list[dict[str, Any]]:
        messages = []
        if self.prompt:
            messages.append(SystemMessage(content=self.prompt).model_dump())
        messages.extend([m.to_openai_dict() for m in self.messages])
        return messages

    def base_payload(self) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": self.to_messages_payload(),
            "stream_options": {"include_usage": True},
        }

        if self.model.startswith("gpt-5"):
            payload["reasoning_effort"] = self.reasoning_effort
        else:
            payload["temperature"] = self.temperature
            payload["top_p"] = self.top_p
            payload["seed"] = self.seed

        return payload

    def to_payload(self) -> dict[str, Any]:
        return self.base_payload()


class OpenAIParserRequest(OpenAIBaseRequest):
    """Support only one tool model for parsing 1 request"""

    tool_models: Annotated[list[type], Field(min_length=1, max_length=1)]
    tool_override: dict | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()

        payload["tools"] = (
            [self.to_function_tools()]
            if not self.tool_override
            else [self.tool_override]
        )
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": self.tool_models[0].__name__},
        }
        return payload

    def to_function_tools(self) -> ChatCompletionFunctionToolParam:
        tool_name = self.tool_models[0].__name__
        tool = pydantic_function_tool(
            self.tool_models[0],
            name=tool_name,
        )
        return tool


class OpenAIChatRequest(OpenAIBaseRequest):
    """Support only sse stream no tool choice"""
    
    max_complete_chat_tokens: int = Field(default = MAX_COMPLETION_TOKENS)

    @model_validator(mode="after")
    def check_sse_stream(self) -> "OpenAIChatRequest":
        if not self.sse_stream:
            raise ValueError("Usage error: sse_stream must be provided")
        return self

    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()
        payload["max_completion_tokens"] = self.max_complete_chat_tokens
        return payload


class OpenAIToolRequest(OpenAIBaseRequest):
    """Support both sse stream and tool choice"""

    tool_models: list[type]

    @model_validator(mode="after")
    def check_tool_models(self) -> "OpenAIToolRequest":
        if not self.tool_models:
            raise ValueError("Usage error: tool_models must be a list of tool models")
        return self

    def to_function_tools(self) -> list[dict]:
        tools = []
        for tool_model in self.tool_models:
            tool_name = tool_model.__name__
            tool = pydantic_function_tool(
                tool_model,
                name=tool_name,
            )
            tools.append(tool)
        return tools

    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()
        payload["tools"] = self.to_function_tools()
        payload["tool_choice"] = "auto"
        return payload
