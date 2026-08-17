import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union

# The one airglider import clients keep: TokenUsage is the data shape the
# app-side @task promotion reads (isinstance-checked). airglider is itself
# standalone, so this survives extraction — same reasoning as planjane/dial.
# No instrumentation here: the steps live on AppWorkflow's wrappers.
from airglider import TokenUsage
from openai.types.chat import ParsedFunctionToolCall
from pydantic import BaseModel, Field
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
    """A tool result on its way back to the model. Pure message shape —
    *running* a tool call is `AppWorkflow.execute_tool_call`, which is where
    the dispatch used to live as a classmethod here and took clients/' last
    piece of instrumentation with it when it moved."""

    role: Literal[Role.TOOL] = Role.TOOL
    name: str
    tool_call_id: str
    content: Any  # tool results only (raw output)
    created: str | None = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
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
