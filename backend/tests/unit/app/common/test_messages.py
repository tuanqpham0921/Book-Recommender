"""Tests for app/common/messages.py"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.chat.parsed_function_tool_call import ParsedFunction, ParsedFunctionToolCall

from app.common.messages import AssistantMessage, SystemMessage, ToolMessage, UserMessage
from common.operation import OperationResult, TokenUsage


def _make_tool_call(call_id="call_abc", name="FindByTitle", arguments='{}') -> ParsedFunctionToolCall:
    return ParsedFunctionToolCall(
        id=call_id,
        type="function",
        function=ParsedFunction(name=name, arguments=arguments),
    )


class TestSystemMessage:
    def test_to_openai_dict(self):
        msg = SystemMessage(content="you are a helpful assistant")
        result = msg.to_openai_dict()
        assert result == {"role": "system", "content": "you are a helpful assistant"}

    def test_role_is_always_system(self):
        msg = SystemMessage(content="x")
        assert msg.role == "system"


class TestUserMessage:
    def test_to_openai_dict_excludes_created(self):
        msg = UserMessage(content="hello")
        result = msg.to_openai_dict()
        assert result == {"role": "user", "content": "hello"}
        assert "created" not in result

    def test_created_is_auto_set(self):
        msg = UserMessage(content="hello")
        assert msg.created is not None

    def test_role_is_always_user(self):
        msg = UserMessage(content="x")
        assert msg.role == "user"


class TestAssistantMessage:
    def test_to_openai_dict_with_content(self):
        msg = AssistantMessage(content="Here are my recommendations.")
        result = msg.to_openai_dict()
        assert result["role"] == "assistant"
        assert result["content"] == "Here are my recommendations."
        assert "tool_calls" not in result

    def test_to_openai_dict_with_tool_calls(self):
        tc = _make_tool_call()
        msg = AssistantMessage(tool_calls=[tc])
        result = msg.to_openai_dict()
        assert result["role"] == "assistant"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_abc"
        assert "content" not in result

    def test_to_openai_dict_omits_metadata(self):
        msg = AssistantMessage(content="hi", id="chatcmpl-xyz")
        result = msg.to_openai_dict()
        assert "id" not in result
        assert "created" not in result
        assert "token_usage" not in result

    def test_token_usage_defaults_to_zero(self):
        msg = AssistantMessage(content="hi")
        assert msg.token_usage == TokenUsage(total=0, prompt=0, completion=0)

    def test_role_is_always_assistant(self):
        msg = AssistantMessage(content="x")
        assert msg.role == "assistant"


class TestToolMessageToOpenaiDict:
    def test_dict_content_serialized_as_json(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content={"title": "Dune"})
        result = msg.to_openai_dict()
        assert result["content"] == json.dumps({"title": "Dune"})

    def test_list_content_serialized_as_json(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content=["a", "b"])
        result = msg.to_openai_dict()
        assert result["content"] == json.dumps(["a", "b"])

    def test_string_content_passed_through(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content="raw string")
        result = msg.to_openai_dict()
        assert result["content"] == "raw string"

    def test_non_string_content_cast_to_string(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content=42)
        result = msg.to_openai_dict()
        assert result["content"] == "42"

    def test_required_keys_always_present(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content="ok")
        result = msg.to_openai_dict()
        assert set(result.keys()) == {"role", "tool_call_id", "content"}

    def test_role_is_always_tool(self):
        msg = ToolMessage(name="FindByTitle", tool_call_id="call_1", content="ok")
        assert msg.role == "tool"


class TestToolMessageExecute:
    def _make_tool_call(self, name: str, output):
        tool_instance = AsyncMock(return_value=output)
        tool_call = MagicMock()
        tool_call.id = "call_abc123"
        tool_call.function.name = name
        tool_call.function.parsed_arguments = tool_instance
        return tool_call

    async def test_returns_operation_result(self):
        tool_call = self._make_tool_call("FindByTitle", {"title": "Dune"})
        result = await ToolMessage.execute(tool_call)
        assert isinstance(result, OperationResult)

    async def test_output_is_tool_message(self):
        tool_call = self._make_tool_call("FindByTitle", {"title": "Dune"})
        result = await ToolMessage.execute(tool_call)
        assert isinstance(result.output, ToolMessage)

    async def test_tool_message_has_correct_name_and_id(self):
        tool_call = self._make_tool_call("FindByTitle", "some output")
        result = await ToolMessage.execute(tool_call)
        msg = result.output
        assert msg.name == "FindByTitle"
        assert msg.tool_call_id == "call_abc123"

    async def test_tool_message_content_is_tool_output(self):
        tool_call = self._make_tool_call("FindByTitle", {"isbn": "123"})
        result = await ToolMessage.execute(tool_call)
        assert result.output.content == {"isbn": "123"}

    async def test_kwargs_forwarded_to_tool(self):
        tool_instance = AsyncMock(return_value="ok")
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "SomeTool"
        tool_call.function.parsed_arguments = tool_instance

        await ToolMessage.execute(tool_call, db="mock_db", user_id=42)
        tool_instance.assert_awaited_once_with(db="mock_db", user_id=42)

    async def test_unwraps_operation_result_output(self):
        tool_call = self._make_tool_call("FindByTitle", OperationResult(ok=True, output={"title": "Dune"}))
        result = await ToolMessage.execute(tool_call)
        assert result.output.content == {"title": "Dune"}

    async def test_unwraps_operation_result_logs_warning(self, caplog):
        import logging
        tool_call = self._make_tool_call("FindByTitle", OperationResult(ok=True, output="some result"))
        with caplog.at_level(logging.WARNING, logger="app.common.messages"):
            await ToolMessage.execute(tool_call)
        assert any("operation result" in r.message for r in caplog.records)

    async def test_exception_captured_as_failed_result(self):
        tool_instance = AsyncMock(side_effect=RuntimeError("db error"))
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "BrokenTool"
        tool_call.function.parsed_arguments = tool_instance

        result = await ToolMessage.execute(tool_call)
        assert result.ok is False
        assert "db error" in result.message
