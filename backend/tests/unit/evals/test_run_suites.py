"""Tests for the query-suite runner: suite loading/filtering, the request
payload it sends (message plus suite_name/suite_case_id so the chat_runs row
links back to its suite entry), and that the default suite path survives
repo restructures."""

import json
from contextlib import contextmanager

import pytest

from evals.run_suites import DEFAULT_SUITE_PATH, load_suite, send_query


SUITE = [
    {"id": 1, "difficulty": "easy", "query": "What is the book Dune?"},
    {"id": 2, "difficulty": "easy", "query": "Recommend me a mystery book."},
    {"id": 3, "difficulty": "medium", "query": "Compare Dune and Hyperion."},
    {"id": 4, "difficulty": "hard", "query": "Plan my next three months of reading."},
]


@pytest.fixture
def suite_path(tmp_path):
    path = tmp_path / "my_suite.json"
    path.write_text(json.dumps(SUITE))
    return path


class TestLoadSuite:
    def test_no_filters_returns_all(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=None)

        assert [e["id"] for e in entries] == [1, 2, 3, 4]

    def test_difficulty_filter(self, suite_path):
        entries = load_suite(suite_path, difficulties=["easy"], ids=None)

        assert [e["id"] for e in entries] == [1, 2]

    def test_multiple_difficulties(self, suite_path):
        entries = load_suite(suite_path, difficulties=["easy", "hard"], ids=None)

        assert [e["id"] for e in entries] == [1, 2, 4]

    def test_ids_filter(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=[3, 1])

        assert [e["id"] for e in entries] == [1, 3]

    def test_filters_combine(self, suite_path):
        entries = load_suite(suite_path, difficulties=["easy"], ids=[2, 3])

        assert [e["id"] for e in entries] == [2]


class FakeClient:
    """Captures the request send_query makes and streams one SSE event back."""

    def __init__(self):
        self.captured = None

    @contextmanager
    def stream(self, method, url, json=None, timeout=None):
        self.captured = {"method": method, "url": url, "json": json}
        yield FakeResponse()


class FakeResponse:
    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(['data: {"type": "content.delta", "data": "hi"}'])


class TestSendQuery:
    def test_payload_carries_suite_link(self):
        client = FakeClient()

        send_query(
            client,
            session_id="test_abc123",
            message="What is the book Dune?",
            suite_name="query_suite",
            suite_case_id=1,
        )

        assert client.captured["method"] == "POST"
        assert client.captured["url"] == "/session/test_abc123/message"
        assert client.captured["json"] == {
            "message": "What is the book Dune?",
            "suite_name": "query_suite",
            "suite_case_id": 1,
        }


class TestDefaultSuitePath:
    def test_default_suite_exists(self):
        # guards the evals/suites/ layout — the runner, the review page's
        # QUERY_SUITES_DIR constant, and the make targets all assume it
        assert DEFAULT_SUITE_PATH.is_file()
        assert DEFAULT_SUITE_PATH.parent.name == "suites"
