"""Tests for the query-suite runner: suite loading/filtering, the request
payload it sends, the chat_id it captures from the chat.id SSE event (used
to write test_runs rows after the run), and that the default suite path
survives repo restructures."""

import argparse
import json
from contextlib import contextmanager

import pytest

from evals.run_suites import (
    DEFAULT_SUITE_PATH,
    load_suite,
    positive_int,
    send_query,
    should_sleep,
)


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
        entries = load_suite(suite_path, difficulties=None, ids=None, limit=None)

        assert [e["id"] for e in entries] == [1, 2, 3, 4]

    def test_difficulty_filter(self, suite_path):
        entries = load_suite(suite_path, difficulties=["easy"], ids=None, limit=None)

        assert [e["id"] for e in entries] == [1, 2]

    def test_multiple_difficulties(self, suite_path):
        entries = load_suite(
            suite_path, difficulties=["easy", "hard"], ids=None, limit=None
        )

        assert [e["id"] for e in entries] == [1, 2, 4]

    def test_ids_filter(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=[3, 1], limit=None)

        assert [e["id"] for e in entries] == [1, 3]

    def test_filters_combine(self, suite_path):
        entries = load_suite(suite_path, difficulties=["easy"], ids=[2, 3], limit=None)

        assert [e["id"] for e in entries] == [2]


class TestLoadSuiteLimit:
    """`--limit` / `make query-suite LIMIT=n` — the debug loop's cap."""

    def test_takes_the_first_n(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=None, limit=2)

        assert [e["id"] for e in entries] == [1, 2]

    def test_applies_after_the_other_filters(self, suite_path):
        # not "first 1 of the file that also happens to be easy" — the cap
        # lands on the filtered set, so ids 1 and 2 survive and 1 is kept
        entries = load_suite(suite_path, difficulties=["easy"], ids=None, limit=1)

        assert [e["id"] for e in entries] == [1]

    def test_limit_larger_than_the_suite_returns_everything(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=None, limit=99)

        assert [e["id"] for e in entries] == [1, 2, 3, 4]

    def test_none_means_no_cap(self, suite_path):
        entries = load_suite(suite_path, difficulties=None, ids=None, limit=None)

        assert len(entries) == len(SUITE)


class TestPositiveInt:
    """--limit's argparse type: the runner should reject a nonsense cap at
    parse time rather than silently running zero queries."""

    def test_accepts_positive(self):
        assert positive_int("3") == 3

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_rejects_zero_and_negative(self, value):
        with pytest.raises(argparse.ArgumentTypeError, match="at least 1"):
            positive_int(value)


class FakeClient:
    """Captures the request send_query makes and streams SSE events back."""

    def __init__(self, lines=None):
        self.captured = None
        self.lines = lines if lines is not None else []

    @contextmanager
    def stream(self, method, url, json=None, timeout=None):
        self.captured = {"method": method, "url": url, "json": json}
        yield FakeResponse(self.lines)


class FakeResponse:
    def __init__(self, lines):
        self.lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self.lines)


class TestSendQuery:
    def test_payload_is_message_only(self):
        client = FakeClient()

        send_query(client, session_id="test_abc123", message="What is the book Dune?")

        assert client.captured["method"] == "POST"
        assert client.captured["url"] == "/session/test_abc123/message"
        assert client.captured["json"] == {"message": "What is the book Dune?"}

    def test_captures_chat_id_from_stream(self):
        client = FakeClient(
            [
                'data: {"type": "chat.id", "data": {"chat_id": "chat_42"}}',
                'data: {"type": "content.delta", "data": "hi"}',
            ]
        )

        chat_id = send_query(client, session_id="test_abc123", message="hello")

        assert chat_id == "chat_42"

    def test_no_chat_id_event_returns_none(self):
        client = FakeClient(['data: {"type": "content.delta", "data": "hi"}'])

        chat_id = send_query(client, session_id="test_abc123", message="hello")

        assert chat_id is None


class TestShouldSleep:
    def test_sleeps_between_queries(self):
        assert should_sleep(1, 4, 45.0) is True

    def test_never_sleeps_after_the_last_query(self):
        assert should_sleep(4, 4, 45.0) is False

    def test_disabled_when_sleep_seconds_is_zero(self):
        assert should_sleep(1, 4, 0) is False

    def test_disabled_when_sleep_seconds_is_negative(self):
        assert should_sleep(1, 4, -5) is False

    def test_single_query_suite_never_sleeps(self):
        assert should_sleep(1, 1, 45.0) is False


class TestDefaultSuitePath:
    def test_default_suite_exists(self):
        # guards the evals/suites/ layout — the runner and the make targets
        # all assume it
        assert DEFAULT_SUITE_PATH.is_file()
        assert DEFAULT_SUITE_PATH.parent.name == "suites"
