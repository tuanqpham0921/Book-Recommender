"""Tests for query_suites: suite-name validation (client-supplied, must not
escape the suites dir), graceful None on missing/malformed files, and the
case summary shape — expected_goal_types derived from expected_system_goals
one-key dicts, None (not empty) when a suite entry defines no expectations."""

import json
import os

import pytest

from app.common import query_suites
from app.common.query_suites import accepted_goal_types, diff_goal_types, get_suite_case
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


def make_planner(*goal_types):
    """chat_runs.planner JSONB shape, down to output.parse_result.accepted_goals."""
    return {
        "output": {
            "parse_result": {
                "accepted_goals": [
                    {"_id": f"goal_{i}", "target_node_type": t, "confidence": 0.9}
                    for i, t in enumerate(goal_types)
                ]
            }
        }
    }


class TestAcceptedGoalTypes:
    def test_extracts_types_in_order(self):
        planner = make_planner("Retrieve_by_Title", "Analyze_Compare")

        assert accepted_goal_types(planner) == ["Retrieve_by_Title", "Analyze_Compare"]

    def test_none_planner(self):
        assert accepted_goal_types(None) == []

    def test_planner_without_parse_result(self):
        # run errored before parsing finished — output holds no parse_result
        assert accepted_goal_types({"output": None}) == []
        assert accepted_goal_types({"output": {}}) == []

    def test_goal_missing_target_node_type_is_skipped(self):
        planner = make_planner("Retrieve_by_Title")
        planner["output"]["parse_result"]["accepted_goals"].append({"_id": "goal_x"})

        assert accepted_goal_types(planner) == ["Retrieve_by_Title"]


class TestDiffGoalTypes:
    def test_exact_match(self):
        diff = diff_goal_types(
            ["Retrieve_by_Title", "Analyze_Compare"],
            ["Analyze_Compare", "Retrieve_by_Title"],
        )

        assert diff == {
            "matched": ["Analyze_Compare", "Retrieve_by_Title"],
            "missing": [],
            "extra": [],
        }

    def test_missing_and_extra(self):
        diff = diff_goal_types(
            ["Retrieve_by_Title", "Analyze_Compare"],
            ["Retrieve_by_Title", "Analyze_Recommend"],
        )

        assert diff == {
            "matched": ["Retrieve_by_Title"],
            "missing": ["Analyze_Compare"],
            "extra": ["Analyze_Recommend"],
        }

    def test_duplicates_count(self):
        # expecting the same type twice but producing it once leaves one missing
        diff = diff_goal_types(
            ["Retrieve_by_Title", "Retrieve_by_Title"],
            ["Retrieve_by_Title"],
        )

        assert diff == {
            "matched": ["Retrieve_by_Title"],
            "missing": ["Retrieve_by_Title"],
            "extra": [],
        }

    def test_no_expectations_returns_none_not_empty_diff(self):
        assert diff_goal_types(None, ["Retrieve_by_Title"]) is None

    def test_run_without_goals_marks_all_expected_missing(self):
        diff = diff_goal_types(["Retrieve_by_Title"], [])

        assert diff == {
            "matched": [],
            "missing": ["Retrieve_by_Title"],
            "extra": [],
        }
