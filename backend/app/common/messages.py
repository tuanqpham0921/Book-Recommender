import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union

from openai.types.chat import ParsedFunctionToolCall
from pydantic import BaseModel, Field, PrivateAttr

from common.operation import OperationResult, TokenUsage, task

logger = logging.getLogger(__name__)

class Role(str, Enum):
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"
    TOOL      = "tool"

class BaseMessage(BaseModel, ABC):
    @abstractmethod
    def to_openai_dict(self) -> dict:
        ...


class SystemMessage(BaseMessage):
    role: Literal[Role.SYSTEM] = Role.SYSTEM
    content: str

    def to_openai_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class UserMessage(BaseMessage):
    role: Literal[Role.USER] = Role.USER
    content: str
    created: str | None = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_openai_dict(self) -> dict:
        return {"role": self.role, "content": self.content}



class AssistantMessage(BaseMessage):
    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    id: str | None = None
    content: str | None = None
    tool_calls: list[ParsedFunctionToolCall] | None = None
    refusal: str | None = None
    created: str | None = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    _token_usage: TokenUsage = PrivateAttr(default_factory=TokenUsage)

    def to_openai_dict(self) -> dict:
        base = {"role": self.role}
        if self.content:
            base["content"] = self.content
        if self.tool_calls:
            base["tool_calls"] = [tc.model_dump(exclude=None) for tc in self.tool_calls]
        return base


class ToolMessage(BaseMessage):
    role: Literal[Role.TOOL] = Role.TOOL
    name: str
    tool_call_id: str
    content: Any  # tool results only (raw output)
    created: str | None = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    
    @classmethod
    @task
    async def execute(cls, tool_call: ParsedFunctionToolCall, **kwargs) -> "ToolMessage":
        tool_name = tool_call.function.name
        tool_instance = tool_call.function.parsed_arguments
        output = await tool_instance(**kwargs)
        
        # TODO: handle this when you have a tool that returns an operation result
        # should keep it in the output field, but not in the content field
        if isinstance(output, OperationResult):
            logger.warning(f"Tool {tool_name} returned an operation result, not a raw output")
        
        return cls(
            name=tool_name,
            tool_call_id=tool_call.id,
            content=output,
        )

    def to_openai_dict(self) -> dict:
        # OpenAI tool messages require string content and no extra fields
        content = self.content
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        else:
            content = str(content)

        return {
            "role": self.role,
            "tool_call_id": self.tool_call_id,
            "content": content,
        }


APIMessage = Annotated[
    Union[SystemMessage, UserMessage, AssistantMessage, ToolMessage],
    Field(discriminator="role"),
]
