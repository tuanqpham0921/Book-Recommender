"""In-process API tests of GET /chat_runs — the endpoint behind the review
(feedback) page. The real FastAPI app is exercised over httpx's ASGI transport
with the chat-run store swapped out via dependency_overrides and the suites
dir pointed at tmp_path — no database, no LLM, no network, so these run in
`make tests-integration` without any services up.

This file is the template for further integration tests: build the rows a
store should serve, get a client from `client_for`, hit the route, assert on
the exact JSON the frontend will receive.
"""

import json

import httpx
import pytest

from app.api.dependencies import get_chat_run_store
from app.common import query_suites
from app.main import app
from config import FilesLocationConstants

pytestmark = pytest.mark.integration


SUITE = [
    {
        "id": 1,
        "difficulty": "easy",
        "query": "What is the book Dune?",
        "note": "Single title lookup.",
        "expected_system_goals": [
            {"Retrieve_by_Title": "Find Dune by title"},
            {"Analyze_Compare": "Compare it to similar books"},
        ],
    },
    {
        "id": 2,
        "difficulty": "easy",
        "query": "Recommend me a mystery book.",
        "note": "No expectations recorded yet.",
    },
]


def make_run(chat_id, *, suite_name="my_suite", suite_case_id=1, goal_types=()):
    """A chat_runs row shaped like ChatRunStore.get_all returns it (to_dict
    plus derived num_reviews), trimmed to the fields this endpoint touches."""
    return {
        "chat_id": chat_id,
        "session_id": "test_integration",
        "user_message": "What is the book Dune?",
        "ok": True,
        "num_reviews": 0,
        "suite_name": suite_name,
        "suite_case_id": suite_case_id,
        "planner": {
            "output": {
                "parse_result": {
                    "accepted_goals": [
                        {
                            "_id": f"goal_{i}",
                            "target_node_type": goal_type,
                            "description": "",
                            "confidence": 0.9,
                        }
                        for i, goal_type in enumerate(goal_types)
                    ]
                }
            }
        },
    }


class FakeChatRunStore:
    def __init__(self, runs):
        self.runs = runs

    async def get_all(self, limit, offset, session_id=None):
        return self.runs


@pytest.fixture
def suites_dir(tmp_path, monkeypatch):
    """Point the suites dir at tmp_path with one suite file written."""
    (tmp_path / "my_suite.json").write_text(json.dumps(SUITE))
    monkeypatch.setattr(FilesLocationConstants, "QUERY_SUITES_DIR", tmp_path)
    query_suites._load_suite_cached.cache_clear()
    return tmp_path


@pytest.fixture
def client_for():
    """Factory: pass the rows the store should serve, get an AsyncClient
    against the real app with that store injected. Overrides are cleared
    after the test so app state never leaks between tests."""

    def _make(runs):
        app.dependency_overrides[get_chat_run_store] = lambda: FakeChatRunStore(runs)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    yield _make
    app.dependency_overrides.clear()


class TestChatRunsSuiteInfo:
    async def test_suite_run_gets_case_and_goal_diff(self, suites_dir, client_for):
        run = make_run("chat_1", goal_types=("Retrieve_by_Title", "Analyze_Recommend"))

        async with client_for([run]) as client:
            resp = await client.get("/chat_runs")

        assert resp.status_code == 200
        [out] = resp.json()["runs"]
        assert out["suite_case"]["note"] == "Single title lookup."
        assert out["suite_case"]["expected_goal_types"] == [
            "Retrieve_by_Title",
            "Analyze_Compare",
        ]
        assert out["goal_diff"] == {
            "matched": ["Retrieve_by_Title"],
            "missing": ["Analyze_Compare"],
            "extra": ["Analyze_Recommend"],
        }

    async def test_clean_run_diff_is_all_matched(self, suites_dir, client_for):
        run = make_run("chat_2", goal_types=("Analyze_Compare", "Retrieve_by_Title"))

        async with client_for([run]) as client:
            resp = await client.get("/chat_runs")

        [out] = resp.json()["runs"]
        assert out["goal_diff"] == {
            "matched": ["Analyze_Compare", "Retrieve_by_Title"],
            "missing": [],
            "extra": [],
        }

    async def test_case_without_expectations_has_no_diff(self, suites_dir, client_for):
        run = make_run("chat_3", suite_case_id=2, goal_types=("Analyze_Recommend",))

        async with client_for([run]) as client:
            resp = await client.get("/chat_runs")

        [out] = resp.json()["runs"]
        assert out["suite_case"]["expected_goal_types"] is None
        assert out["goal_diff"] is None

    async def test_unknown_case_id_still_returns_run(self, suites_dir, client_for):
        run = make_run("chat_4", suite_case_id=999, goal_types=("Retrieve_by_Title",))

        async with client_for([run]) as client:
            resp = await client.get("/chat_runs")

        [out] = resp.json()["runs"]
        assert out["chat_id"] == "chat_4"
        assert out["suite_case"] is None
        assert out["goal_diff"] is None

    async def test_regular_user_run_gets_no_suite_fields(self, suites_dir, client_for):
        run = make_run("chat_5", suite_name=None, suite_case_id=None)

        async with client_for([run]) as client:
            resp = await client.get("/chat_runs")

        [out] = resp.json()["runs"]
        assert "suite_case" not in out
        assert "goal_diff" not in out
