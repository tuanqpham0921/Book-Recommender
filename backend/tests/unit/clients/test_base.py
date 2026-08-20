import pytest
from typing import Any
from app.common.messages import UserMessage
from clients.base import BaseLLMClient, BaseLLMRequest


class ConcreteRequest(BaseLLMRequest):
    def to_payload(self) -> dict[str, Any]:
        return {"model": self.model}


class ConcreteClient(BaseLLMClient):
    max_tokens = 100

    async def execute(self, *_): ...
    async def close(self): ...
    def token_count(self, text): return len(text)
    async def ping(self): return True


USER_MSG = UserMessage(content="hello")


class TestBaseLLMRequest:
    def test_instantiates_with_required_fields(self):
        req = ConcreteRequest(prompt="p", messages=[USER_MSG], model="gpt-4")
        assert req.prompt == "p"
        assert req.model == "gpt-4"
        assert req.sse_stream is None

    def test_to_payload_called(self):
        req = ConcreteRequest(prompt="p", messages=[USER_MSG], model="gpt-4")
        assert req.to_payload() == {"model": "gpt-4"}

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseLLMRequest(prompt="p", messages=[USER_MSG], model="gpt-4")


class TestBaseLLMClient:
    def setup_method(self):
        self.client = ConcreteClient()

    def test_over_max_tokens_true(self):
        assert self.client.over_max_tokens(101) is True

    def test_over_max_tokens_false(self):
        assert self.client.over_max_tokens(100) is False

    def test_over_max_tokens_exact_limit(self):
        assert self.client.over_max_tokens(10) is False
