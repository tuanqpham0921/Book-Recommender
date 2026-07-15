"""Tests for query_suites: suite-name validation (client-supplied, must not
escape the suites dir), graceful None on missing/malformed files, and the
case summary shape — expected_goal_types derived from expected_system_goals
one-key dicts, None (not empty) when a suite entry defines no expectations."""

import json
import os

import pytest

from app.common import query_suites
from app.common.query_suites import get_suite_case
from config import FilesLocationConstants


SUITE = [
    {
        "id": 1,
        "difficulty": "easy",
        "query": "What is the book Dune?",
        "note": "Single FindByTitle.",
        "expected_system_goals": [
            {"Retrieve_by_Title": "Find Dune by title"},
            {"Analyze_Summarize": "Summarize the book Dune"},
        ],
    },
    {
        "id": 2,
        "difficulty": "easy",
        "query": "Recommend me a mystery book.",
        "note": "No expectations recorded yet.",
    },
    {
        "id": 3,
        "difficulty": "medium",
        "query": "Compare Dune and Hyperion.",
        "note": "Legacy shape only.",
        "expected_nodes": ["Retrieve_by_Title", "Analyze_Compare"],
    },
]


@pytest.fixture
def suites_dir(tmp_path, monkeypatch):
    """Point the suites dir at tmp_path with one suite file written."""
    (tmp_path / "my_suite.json").write_text(json.dumps(SUITE))
    monkeypatch.setattr(FilesLocationConstants, "QUERY_SUITES_DIR", tmp_path)
    query_suites._load_suite_cached.cache_clear()
    return tmp_path


class TestGetSuiteCase:
    def test_case_with_expected_system_goals(self, suites_dir):
        case = get_suite_case("my_suite", 1)

        assert case["suite_name"] == "my_suite"
        assert case["id"] == 1
        assert case["difficulty"] == "easy"
        assert case["query"] == "What is the book Dune?"
        assert case["note"] == "Single FindByTitle."
        assert case["expected_goal_types"] == [
            "Retrieve_by_Title",
            "Analyze_Summarize",
        ]
        assert case["expected_nodes"] is None

    def test_case_without_expectations_flags_none(self, suites_dir):
        case = get_suite_case("my_suite", 2)

        assert case["expected_goal_types"] is None
        assert case["expected_nodes"] is None

    def test_legacy_expected_nodes_passthrough(self, suites_dir):
        case = get_suite_case("my_suite", 3)

        assert case["expected_goal_types"] is None
        assert case["expected_nodes"] == ["Retrieve_by_Title", "Analyze_Compare"]

    def test_unknown_case_id_returns_none(self, suites_dir):
        assert get_suite_case("my_suite", 999) is None

    def test_missing_suite_file_returns_none(self, suites_dir):
        assert get_suite_case("no_such_suite", 1) is None

    def test_none_inputs_return_none(self, suites_dir):
        assert get_suite_case(None, 1) is None
        assert get_suite_case("my_suite", None) is None

    def test_path_traversal_name_rejected(self, suites_dir):
        (suites_dir.parent / "outside.json").write_text(json.dumps(SUITE))

        assert get_suite_case("../outside", 1) is None

    def test_malformed_json_returns_none(self, suites_dir):
        (suites_dir / "broken.json").write_text("not json")

        assert get_suite_case("broken", 1) is None

    def test_cache_invalidates_when_file_changes(self, suites_dir):
        path = suites_dir / "my_suite.json"
        assert get_suite_case("my_suite", 1)["difficulty"] == "easy"

        updated = json.loads(path.read_text())
        updated[0]["difficulty"] = "hard"
        path.write_text(json.dumps(updated))
        # force a distinct mtime — same-second writes can otherwise collide
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 1))

        assert get_suite_case("my_suite", 1)["difficulty"] == "hard"
