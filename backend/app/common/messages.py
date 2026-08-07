import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union, cast

from openai.types.chat import ParsedFunctionToolCall
from pydantic import BaseModel, Field
from common.operation import OperationResult, TokenUsage, task
from common.utils import to_serializable, remove_empty_values, uuid_8

logger = logging.getLogger(__name__)


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class BaseMessage(BaseModel, ABC):
    @abstractmethod
    def to_openai_dict(self) -> dict: ...


class SystemMessage(BaseMessage):
    role: Literal[Role.SYSTEM] = Role.SYSTEM
    content: str

    def to_openai_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class UserMessage(BaseMessage):
    role: Literal[Role.USER] = Role.USER
    id: str = Field(default_factory=lambda: f"chat_{uuid_8()}")
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
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def to_openai_dict(self) -> dict:
        base: dict[str, Any] = {"role": self.role}
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
    async def execute(
        cls, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> "ToolMessage":
        tool_name = tool_call.function.name
        # parsed_arguments is typed `object | None` by the openai lib; the
        # parser validated it into a callable node instance
        tool_instance = cast(Any, tool_call.function.parsed_arguments)
        output = await tool_instance(**kwargs)

        # NOTE: make sure the tool calls return just the output
        if isinstance(output, OperationResult):
            logger.warning(
                f"Tool {tool_name} returned an operation result, not a raw output"
            )
            output = output.response.output

        return cls(
            name=tool_name,
            tool_call_id=tool_call.id,
            content=output,
        )

    def to_openai_dict(self) -> dict:
        # OpenAI tool messages require string content and no extra fields
        # content can be pydantic
        content = self.content
        if content is None:
            content = ""
        elif not isinstance(content, str):
            jsonable = to_serializable(content)
            jsonable = remove_empty_values(jsonable)
            content = json.dumps(jsonable)

        return {
            "role": self.role,
            "tool_call_id": self.tool_call_id,
            "content": content,
        }


APIMessage = Annotated[
    Union[SystemMessage, UserMessage, AssistantMessage, ToolMessage],
    Field(discriminator="role"),
]
