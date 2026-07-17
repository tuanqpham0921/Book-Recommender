"""In-process API tests of GET /chat_runs — the endpoint behind the review
(feedback) page. The real FastAPI app is exercised over httpx's ASGI transport
with the chat-run store swapped out via dependency_overrides — no database,
no LLM, no network, so these run in `make tests-integration` without any
services up.

This file is the template for further integration tests: build the rows a
store should serve, get a client from `client_for`, hit the route, assert on
the exact JSON the frontend will receive.
"""

import httpx
import pytest

from app.api.dependencies import get_chat_run_store
from app.main import app

pytestmark = pytest.mark.integration


def make_run(chat_id, *, num_reviews=0):
    """A chat_runs row shaped like ChatRunStore.get_all returns it (to_dict
    plus derived num_reviews), trimmed to the fields this endpoint touches."""
    return {
        "chat_id": chat_id,
        "session_id": "test_integration",
        "user_message": "What is the book Dune?",
        "ok": True,
        "num_reviews": num_reviews,
    }


class FakeChatRunStore:
    def __init__(self, runs):
        self.runs = runs
        self.calls = []

    async def get_all(self, limit, offset, session_id=None):
        self.calls.append({"limit": limit, "offset": offset, "session_id": session_id})
        return self.runs


@pytest.fixture
def client_for():
    """Factory: pass the store the endpoint should use, get an AsyncClient
    against the real app with that store injected. Overrides are cleared
    after the test so app state never leaks between tests."""

    def _make(store):
        app.dependency_overrides[get_chat_run_store] = lambda: store
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    yield _make
    app.dependency_overrides.clear()


class TestListChatRuns:
    async def test_returns_store_rows_unchanged(self, client_for):
        runs = [make_run("chat_1"), make_run("chat_2", num_reviews=3)]
        store = FakeChatRunStore(runs)

        async with client_for(store) as client:
            resp = await client.get("/chat_runs")

        assert resp.status_code == 200
        assert resp.json() == {"runs": runs}

    async def test_query_params_reach_the_store(self, client_for):
        store = FakeChatRunStore([])

        async with client_for(store) as client:
            resp = await client.get(
                "/chat_runs", params={"limit": 5, "offset": 10, "session_id": "test_"}
            )

        assert resp.status_code == 200
        assert store.calls == [{"limit": 5, "offset": 10, "session_id": "test_"}]

    async def test_limit_out_of_bounds_is_rejected(self, client_for):
        store = FakeChatRunStore([])

        async with client_for(store) as client:
            resp = await client.get("/chat_runs", params={"limit": 1001})

        assert resp.status_code == 422
