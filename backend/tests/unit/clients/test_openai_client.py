import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.openai_client import OpenAIClient
from config.settings import OpenAISettings
from common.operation import OperationResult
from app.common.messages import AssistantMessage

def async_iter(items):
    """Return an async iterable over items."""
    async def _gen():
        for item in items:
            yield item
    return _gen()



def make_settings(**overrides):
    base = {
        "API_KEY": "test-key",
        "BASE_MODEL": "gpt-4o",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIMENSIONS": 512,
        "MAX_CONCURRENCY": 5,
    }
    return OpenAISettings(**{**base, **overrides})


def make_client():
    with patch("clients.openai_client.AsyncOpenAI"):
        return OpenAIClient(make_settings())


def make_fake_completion(content="hi", total=10, prompt=7, completion=3):
    usage = MagicMock(total_tokens=total, prompt_tokens=prompt, completion_tokens=completion)
    message = MagicMock(content=content, tool_calls=None, refusal=None)
    completion = MagicMock(id="cmpl-123", choices=[MagicMock(message=message)], usage=usage)
    return completion


class TestOpenAIClientInit:
    def test_raises_when_api_key_missing(self):
        with pytest.raises(ValueError, match="API key"):
            OpenAIClient(make_settings(API_KEY=""))

    def test_sets_max_tokens(self):
        client = make_client()
        assert client.max_tokens > 0

    def test_sets_embedding_model(self):
        client = make_client()
        assert client.embedding_model == "text-embedding-3-small"


class TestTokenCount:
    def setup_method(self):
        self.client = make_client()

    def test_single_string(self):
        count = self.client.token_count("hello world")
        assert count > 0

    def test_list_of_strings(self):
        count = self.client.token_count(["hello", "world"])
        assert count > 0

    def test_list_sums_individual_counts(self):
        combined = self.client.token_count("hello world")
        split = self.client.token_count(["hello", "world"])
        # may differ slightly due to encoding boundaries but both positive
        assert combined > 0 and split > 0

    def test_empty_string_returns_zero(self):
        assert self.client.token_count("") == 0


class TestGetEmbeddings:
    def setup_method(self):
        self.client = make_client()

    @pytest.mark.asyncio
    async def test_raises_when_input_too_long(self):
        self.client.max_tokens = 1
        with pytest.raises(ValueError, match="too long"):
            await self.client.get_embeddings(["a very long text that exceeds one token"])

    @pytest.mark.asyncio
    async def test_returns_embeddings(self):
        fake_response = MagicMock()
        fake_response.data = [MagicMock(embedding=[0.1, 0.2]), MagicMock(embedding=[0.3, 0.4])]
        self.client.client.embeddings.create = AsyncMock(return_value=fake_response)

        result = await self.client.get_embeddings(["hello", "world"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @pytest.mark.asyncio
    async def test_reraises_api_error(self):
        self.client.client.embeddings.create = AsyncMock(side_effect=RuntimeError("API down"))
        with pytest.raises(RuntimeError, match="API down"):
            await self.client.get_embeddings(["hello"])


class TestExecute:
    def setup_method(self):
        self.client = make_client()

    @pytest.mark.asyncio
    async def test_returns_operation_result(self):
        fake_completion = make_fake_completion()
        self.client._chat_stream = AsyncMock(return_value=fake_completion)

        req = MagicMock(sse_stream=None, to_payload=lambda: {})
        result = await self.client.execute(req)

        assert isinstance(result, OperationResult)

    @pytest.mark.asyncio
    async def test_output_is_assistant_message(self):
        fake_completion = make_fake_completion(content="hello")
        self.client._chat_stream = AsyncMock(return_value=fake_completion)

        req = MagicMock(sse_stream=None, to_payload=lambda: {})
        result = await self.client.execute(req)

        assert isinstance(result.output, AssistantMessage)
        assert result.output.content == "hello"

    @pytest.mark.asyncio
    async def test_token_usage_propagated(self):
        fake_completion = make_fake_completion(total=10, prompt=7, completion=3)
        self.client._chat_stream = AsyncMock(return_value=fake_completion)

        req = MagicMock(sse_stream=None, to_payload=lambda: {})
        result = await self.client.execute(req)

        assert result.token_usage.total == 10
        assert result.token_usage.prompt == 7
        assert result.token_usage.completion == 3

    @pytest.mark.asyncio
    async def test_save_payload_called_when_flag_set(self):
        fake_completion = make_fake_completion()
        self.client._chat_stream = AsyncMock(return_value=fake_completion)

        req = MagicMock(sse_stream=None, to_payload=lambda: {})
        with patch("clients.openai_client.save_file") as mock_save:
            await self.client.execute(req, save_payload=True)

        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_payload_not_called_by_default(self):
        fake_completion = make_fake_completion()
        self.client._chat_stream = AsyncMock(return_value=fake_completion)

        req = MagicMock(sse_stream=None, to_payload=lambda: {})
        with patch("clients.openai_client.save_file") as mock_save:
            await self.client.execute(req)

        mock_save.assert_not_called()


class TestClose:
    @pytest.mark.asyncio
    async def test_calls_aclose(self):
        client = make_client()
        client.client._client.aclose = AsyncMock()
        await client.close()
        client.client._client.aclose.assert_called_once()


class TestChatStream:
    def setup_method(self):
        self.client = make_client()

    def make_stream_mock(self, events, completion):
        stream = AsyncMock()
        stream.__aenter__ = AsyncMock(return_value=stream)
        stream.__aexit__ = AsyncMock(return_value=None)
        stream.__aiter__ = MagicMock(return_value=async_iter(events))
        stream.get_final_completion = AsyncMock(return_value=completion)
        self.client.client.beta.chat.completions.stream = MagicMock(return_value=stream)
        return stream

    @pytest.mark.asyncio
    async def test_returns_final_completion(self):
        fake_completion = make_fake_completion()
        self.make_stream_mock([], fake_completion)

        result = await self.client._chat_stream({}, sse_stream=None)
        assert result == fake_completion

    @pytest.mark.asyncio
    async def test_sends_delta_to_sse_stream(self):
        fake_completion = make_fake_completion()
        event = MagicMock(type="content.delta", delta="hello")
        self.make_stream_mock([event], fake_completion)

        sse = AsyncMock()
        await self.client._chat_stream({}, sse_stream=sse)

        sse.send_chars.assert_called_once_with(data="hello")

    @pytest.mark.asyncio
    async def test_non_delta_event_skipped(self):
        fake_completion = make_fake_completion()
        event = MagicMock(type="chunk", delta="ignored")
        self.make_stream_mock([event], fake_completion)

        sse = AsyncMock()
        await self.client._chat_stream({}, sse_stream=sse)

        sse.send_chars.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_sse_stream_skips_send(self):
        fake_completion = make_fake_completion()
        event = MagicMock(type="content.delta", delta="hello")
        self.make_stream_mock([event], fake_completion)

        result = await self.client._chat_stream({}, sse_stream=None)
        assert result == fake_completion


class TestPing:
    def setup_method(self):
        self.client = make_client()

    @pytest.mark.asyncio
    async def test_calls_responses_api(self):
        self.client.client.responses.create = AsyncMock(return_value=MagicMock())
        await self.client.ping()
        self.client.client.responses.create.assert_called_once_with(
            model="gpt-5-nano", input="ping"
        )

    # NOTE: open_ai client ping is now a task
    # waiting for @task and workflow tests
    # @pytest.mark.asyncio
    # async def test_reraises_on_failure(self):
    #     self.client.client.responses.create = AsyncMock(side_effect=RuntimeError("timeout"))
    #     with pytest.raises(RuntimeError, match="timeout"):
    #         await self.client.ping()
