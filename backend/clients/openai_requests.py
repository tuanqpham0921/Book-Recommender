import logging
from dataclasses import dataclass
from typing import Any

from .base import BaseLLMRequest

from config import settings
from app.common.messages import SystemMessage
from openai import pydantic_function_tool
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

MAX_COMPLETION_TOKENS = 50
TEMPERATURE = 0.3
TOP_P = 0.8
SEED = 42

@dataclass(kw_only=True)
class OpenAIBaseRequest(BaseLLMRequest):
    model: str = settings.openai.BASE_MODEL
    temperature: float = TEMPERATURE
    top_p: float = TOP_P
    seed: int = SEED

    def to_messages_payload(self) -> list[dict[str, Any]]:
        messages = []
        if self.prompt:
            messages.append(SystemMessage(content=self.prompt).model_dump())
        messages.extend([m.to_openai_dict() for m in self.messages])
        return messages

    def base_payload(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": self.to_messages_payload(),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
        }
    
    def to_payload(self) -> dict[str, Any]:
        return self.base_payload()

@dataclass(kw_only=True)
class OpenAIParserRequest(OpenAIBaseRequest):
    """ Support only one tool model for parsing 1 request"""
    tool_models: list[type]
    tool_override: dict | None = None
    
    def __post_init__(self):
        if len(self.tool_models) != 1:
            raise ValueError("tool_models must be a list of exactly one tool model")

    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()

        payload["tools"] = [self.to_function_tools()] if not self.tool_override else [self.tool_override]
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": self.tool_models[0].__name__},
        }
        return payload

    def to_function_tools(self) -> list[dict]:
        tool_name = self.tool_models[0].__name__
        tool = pydantic_function_tool(
            self.tool_models[0],
            name=tool_name,
            description=f"Fill the schema for {tool_name}",
        )
        return tool

@dataclass(kw_only=True)
class OpenAIChatRequest(OpenAIBaseRequest):
    """ Support only sse stream """
    def __post_init__(self):
        if not self.sse_stream:
            raise ValueError("Usage error: sse_stream must be provided")
        
    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()
        if self.sse_stream:
            payload["max_completion_tokens"] = MAX_COMPLETION_TOKENS
        return payload
    
@dataclass(kw_only=True)
class OpenAIToolRequest(OpenAIBaseRequest):
    """ Support both sse stream and tool choice """
    tool_models: list[type]
    def __post_init__(self):
        if not self.tool_models:
            raise ValueError("Usage error: tool_models must be a list of tool models")
        
    def to_function_tools(self) -> list[dict]:
        tools = []
        for tool_model in self.tool_models:
            tool_name = tool_model.__name__
            tool = pydantic_function_tool(
                tool_model,
                name=tool_name,
                # TODO: this is a different description for each tool
                # and different from the parser request
                description=f"Fill the schema for {tool_name}", 
            )
            tools.append(tool)
        return tools
    
    def to_payload(self) -> dict[str, Any]:
        payload = self.base_payload()
        payload["tools"] = self.to_function_tools()
        payload["tool_choice"] = "auto" if len(self.tool_models) else "none"
        return payload
    