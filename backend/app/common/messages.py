import json

from pytz import UTC
from datetime import datetime
from typing_extensions import Annotated
from pydantic import BaseModel, Field
from openai.types.chat import ParsedFunctionToolCall
from typing import Union, Dict, Optional, List, Literal, Any
from enum import Enum

from abc import ABC, abstractmethod
import logging
from common.operation import OperationResult, task

logger = logging.getLogger(__name__)

class Role(str, Enum):
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"
    TOOL      = "tool"

class BaseMessage(BaseModel, ABC):
    @abstractmethod
    def to_openai_dict(self) -> Dict:
        ...
    
class SystemMessage(BaseMessage):
    role: Literal[Role.SYSTEM] = Role.SYSTEM
    content: str

    def to_openai_dict(self) -> Dict:
        return {"role": self.role, "content": self.content}


class UserMessage(BaseMessage):
    role: Literal[Role.USER] = Role.USER
    content: str
    created: Optional[str] = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_openai_dict(self) -> Dict:
        return {"role": self.role, "content": self.content}

class TokenUsage(BaseModel):
    total: int = Field(default=0)
    prompt: int = Field(default=0)
    completion: int = Field(default=0)

class AssistantMessage(BaseMessage):
    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    id: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[ParsedFunctionToolCall]] = None
    refusal: Optional[str] = None
    created: Optional[str] = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def to_openai_dict(self) -> Dict:
        base = {"role": self.role}
        if self.content:
            base["content"] = self.content
        if self.tool_calls:
            # convert each tool call to OpenAI schema (list of dicts)
            base["tool_calls"] = [tc.model_dump(exclude=None) for tc in self.tool_calls]
        return base


class ToolMessage(BaseMessage):
    role: Literal[Role.TOOL] = Role.TOOL
    name: str
    tool_call_id: str
    content: Any  # tool results only (raw output)
    created: Optional[str] = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
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

    def to_openai_dict(self) -> Dict:
        # TODO: unit test this for other types of content
        # OpenAI tool messages require string content and no extra fields like name/elapsed
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
