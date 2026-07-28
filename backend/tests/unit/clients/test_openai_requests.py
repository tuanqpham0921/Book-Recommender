import pytest
from unittest.mock import MagicMock
from openai.lib._parsing._completions import is_parseable_tool
from pydantic import BaseModel

from app.common.messages import AssistantMessage, ToolMessage, UserMessage
from app.common.sse_stream import SSEStream
from clients.openai_requests import (
    MAX_COMPLETION_TOKENS,
    SEED,
    TEMPERATURE,
    TOP_P,
    OpenAIBaseRequest,
    OpenAIChatRequest,
    OpenAIParserRequest,
    OpenAIToolRequest,
)


USER_MSG = UserMessage(content="hello")


def make_sse_stream():
    return SSEStream()


class ToolA(BaseModel):
    query: str


class ToolB(BaseModel):
    isbn: str


class DocumentedTool(BaseModel):
    """Purpose: pick this tool when the user names a title."""

    query: str


class TestOpenAIBaseRequest:
    def test_defaults(self):
        req = OpenAIBaseRequest(prompt="p", messages=[USER_MSG])
        assert req.temperature == TEMPERATURE
        assert req.top_p == TOP_P
        assert req.seed == SEED

    def test_base_payload_keys(self):
        req = OpenAIBaseRequest(prompt="p", messages=[USER_MSG])
        payload = req.base_payload()
        assert set(payload.keys()) == {"model", "messages", "temperature", "top_p", "seed", "stream_options"}

    def test_base_payload_includes_stream_options(self):
        req = OpenAIBaseRequest(prompt="p", messages=[USER_MSG])
        assert req.base_payload()["stream_options"] == {"include_usage": True}

    def test_to_messages_payload_includes_system_message(self):
        req = OpenAIBaseRequest(prompt="be helpful", messages=[USER_MSG])
        msgs = req.to_messages_payload()
        roles = [m["role"] for m in msgs]
        assert "system" in roles
        assert "user" in roles

    def test_to_messages_payload_no_prompt(self):
        req = OpenAIBaseRequest(prompt="", messages=[USER_MSG])
        msgs = req.to_messages_payload()
        assert all(m["role"] != "system" for m in msgs)

    def test_to_payload_returns_base_payload(self):
        req = OpenAIBaseRequest(prompt="p", messages=[USER_MSG])
        assert req.to_payload() == req.base_payload()

    def test_tool_message_without_assistant_tool_call_raises(self):
        tool_msg = ToolMessage(name="search", tool_call_id="tc_1", content="result")
        with pytest.raises(ValueError, match="no matching assistant tool_call"):
            OpenAIBaseRequest(prompt="p", messages=[USER_MSG, tool_msg])

    def test_unanswered_assistant_tool_call_raises(self):
        assistant_msg = AssistantMessage.model_construct(tool_calls=[MagicMock(id="tc_1")])
        with pytest.raises(ValueError, match="no ToolMessage reply"):
            OpenAIBaseRequest(prompt="p", messages=[USER_MSG, assistant_msg])

    def test_matched_tool_call_and_reply_passes(self):
        assistant_msg = AssistantMessage.model_construct(tool_calls=[MagicMock(id="tc_1")])
        tool_msg = ToolMessage(name="search", tool_call_id="tc_1", content="result")
        req = OpenAIBaseRequest(prompt="p", messages=[USER_MSG, assistant_msg, tool_msg])
        payload = req.to_messages_payload()
        assert len(payload) == 4  # system + user + assistant + tool


class TestOpenAIParserRequest:
    def test_accepts_exactly_one_tool_model(self):
        req = OpenAIParserRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA])
        assert req.tool_models == [ToolA]

    def test_rejects_empty_tool_models(self):
        with pytest.raises(Exception):
            OpenAIParserRequest(prompt="p", messages=[USER_MSG], tool_models=[])

    def test_rejects_more_than_one_tool_model(self):
        with pytest.raises(Exception):
            OpenAIParserRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA, ToolB])

    def test_to_payload_has_tools_and_tool_choice(self):
        req = OpenAIParserRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA])
        payload = req.to_payload()
        assert "tools" in payload
        assert payload["tool_choice"]["function"]["name"] == "ToolA"

    def test_docstring_is_sent_as_description_by_default(self):
        req = OpenAIParserRequest(
            prompt="p", messages=[USER_MSG], tool_models=[DocumentedTool]
        )
        tool = req.to_function_tools()
        assert tool["function"]["description"] == DocumentedTool.__doc__

    def test_description_dropped_when_disabled(self):
        req = OpenAIParserRequest(
            prompt="p",
            messages=[USER_MSG],
            tool_models=[DocumentedTool],
            include_tool_description=False,
        )
        tool = req.to_function_tools()
        assert "description" not in tool["function"]
        # dropping it must not cost us auto-parsing: the openai lib keys that off
        # tool["function"] still being a PydanticFunctionTool carrying .model
        assert is_parseable_tool(tool)
        assert tool["function"].model is DocumentedTool

    def test_to_payload_uses_tool_override(self):
        override = {"type": "function", "function": {"name": "custom"}}
        req = OpenAIParserRequest(
            prompt="p", messages=[USER_MSG], tool_models=[ToolA], tool_override=override
        )
        payload = req.to_payload()
        assert payload["tools"] == [override]


class TestOpenAIChatRequest:
    def test_requires_sse_stream(self):
        with pytest.raises(ValueError, match="sse_stream"):
            OpenAIChatRequest(prompt="p", messages=[USER_MSG])

    def test_accepts_sse_stream(self):
        req = OpenAIChatRequest(prompt="p", messages=[USER_MSG], sse_stream=make_sse_stream())
        assert req.sse_stream is not None

    def test_to_payload_has_max_completion_tokens(self):
        req = OpenAIChatRequest(prompt="p", messages=[USER_MSG], sse_stream=make_sse_stream())
        assert req.to_payload()["max_completion_tokens"] == MAX_COMPLETION_TOKENS

    def test_custom_max_completion_tokens(self):
        req = OpenAIChatRequest(
            prompt="p", messages=[USER_MSG], sse_stream=make_sse_stream(), max_complete_chat_tokens=50
        )
        assert req.to_payload()["max_completion_tokens"] == 50


class TestOpenAIToolRequest:
    def test_accepts_multiple_tool_models(self):
        req = OpenAIToolRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA, ToolB])
        assert len(req.tool_models) == 2

    def test_rejects_empty_tool_models(self):
        with pytest.raises(ValueError, match="tool_models"):
            OpenAIToolRequest(prompt="p", messages=[USER_MSG], tool_models=[])

    def test_to_payload_has_tools(self):
        req = OpenAIToolRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA])
        payload = req.to_payload()
        assert "tools" in payload
        assert len(payload["tools"]) == 1

    def test_tool_choice_auto_with_models(self):
        req = OpenAIToolRequest(prompt="p", messages=[USER_MSG], tool_models=[ToolA])
        assert req.to_payload()["tool_choice"] == "auto"
