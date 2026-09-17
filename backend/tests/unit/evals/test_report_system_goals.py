"""Tests for the system-goals report's pure parts: extracting accepted goal
types from a recorded planner envelope, the expected-vs-accepted multiset
diff, per-case verdicts, and the rendered markdown. The DB shim (fetch_rows)
is deliberately thin and not covered here.

Token/cost/latency reporting lives in report.py and is tested in
test_report.py — this report deliberately says nothing about them.
"""

import json
from datetime import datetime, timezone

import pytest

import evals.common as common_module
from evals.common import latest_per_case, load_suite_entries
from evals.report_system_goals import (
    accepted_goal_types,
    build_goals_report,
    diff_node_types,
    evaluate_row,
)


def make_planner(*goal_types, token_usage=None):
    planner = {
        "response": {
            "result": {
                "parse_result": {
                    "accepted_goals": [
                        {"_id": f"goal_{i}", "target_node_type": goal_type}
                        for i, goal_type in enumerate(goal_types)
                    ]
                }
            }
        }
    }
    if token_usage is not None:
        planner["token_usage"] = token_usage
    return planner


def make_row(
    case_id,
    *,
    suite_name="my_suite",
    chat_id=None,
    goal_types=(),
    token_usage=None,
    **overrides,
):
    row = {
        "suite_name": suite_name,
        "suite_case_id": case_id,
        "chat_id": chat_id or f"chat_{suite_name}_{case_id}",
        "session_id": "test_abc123",
        "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "ok": True,
        "runtime_error": None,
        "user_message": "recorded message",
        "planner": make_planner(*goal_types, token_usage=token_usage),
    }
    row.update(overrides)
    return row


class TestAcceptedGoalTypes:
    def test_extracts_types_in_order(self):
        planner = make_planner("Retrieve_by_Title", "Analyze_Similar_Books")

        assert accepted_goal_types(planner) == [
            "Retrieve_by_Title",
            "Analyze_Similar_Books",
        ]

    def test_missing_parse_result_is_empty(self):
        # e.g. the run errored before parsing finished
        assert accepted_goal_types({"response": {"result": {}}}) == []
        assert accepted_goal_types(None) == []

    def test_malformed_goals_are_skipped(self):
        planner = {
            "response": {
                "result": {
                    "parse_result": {
                        "accepted_goals": [
                            {"target_node_type": "Retrieve_by_Title"},
                            {"target_node_type": 42},
                            "not a dict",
                        ]
                    }
                }
            }
        }

        assert accepted_goal_types(planner) == ["Retrieve_by_Title"]


class TestDiffNodeTypes:
    def test_exact_match(self):
        diff = diff_node_types(["A", "B"], ["B", "A"])

        assert diff == {"matched": ["A", "B"], "missing": [], "extra": []}

    def test_missing_and_extra(self):
        diff = diff_node_types(["A", "B"], ["A", "C"])

        assert diff == {"matched": ["A"], "missing": ["B"], "extra": ["C"]}

    def test_duplicates_count(self):
        # expecting A twice but producing it once leaves one missing
        diff = diff_node_types(["A", "A"], ["A"])

        assert diff == {"matched": ["A"], "missing": ["A"], "extra": []}

    def test_no_expectations_is_none_not_empty(self):
        assert diff_node_types(None, ["A"]) is None


class TestEvaluateRow:
    def test_match(self):
        row = make_row(1, goal_types=("Retrieve_by_Title",))

        verdict = evaluate_row(row, {"expected_nodes": ["Retrieve_by_Title"]})

        assert verdict["status"] == "match"

    def test_mismatch_on_extra(self):
        row = make_row(1, goal_types=("Retrieve_by_Title", "Analyze_Summarize"))

        verdict = evaluate_row(row, {"expected_nodes": ["Retrieve_by_Title"]})

        assert verdict["status"] == "mismatch"
        assert verdict["diff"]["extra"] == ["Analyze_Summarize"]

    def test_mismatch_on_missing(self):
        row = make_row(1, goal_types=())

        verdict = evaluate_row(row, {"expected_nodes": ["Retrieve_by_Title"]})

        assert verdict["status"] == "mismatch"
        assert verdict["diff"]["missing"] == ["Retrieve_by_Title"]

    def test_entry_without_expected_nodes(self):
        row = make_row(1, goal_types=("Retrieve_by_Title",))

        verdict = evaluate_row(row, {"note": "no expectations yet"})

        assert verdict["status"] == "no_expectations"
        assert verdict["diff"] is None

    def test_case_missing_from_suite_json(self):
        # entries.get(case_id, {}) hands evaluate_row an empty entry
        verdict = evaluate_row(make_row(99), {})

        assert verdict["status"] == "no_expectations"


class TestLatestPerCase:
    def test_keeps_last_row_per_case(self):
        # fetch_rows orders by created_at within a case, so last wins
        old = make_row(1, chat_id="chat_old")
        new = make_row(1, chat_id="chat_new")
        other = make_row(2)

        kept = latest_per_case([old, new, other])

        assert {r["chat_id"] for r in kept} == {"chat_new", "chat_my_suite_2"}

    def test_same_case_id_in_different_suites_both_kept(self):
        rows = [make_row(1, suite_name="suite_a"), make_row(1, suite_name="suite_b")]

        assert len(latest_per_case(rows)) == 2


class TestLoadSuiteEntries:
    @pytest.fixture
    def suites_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(common_module, "SUITES_DIR", tmp_path)
        return tmp_path

    def test_maps_entries_by_id(self, suites_dir):
        (suites_dir / "my_suite.json").write_text(
            json.dumps([{"id": 1, "query": "q1"}, {"id": 2, "query": "q2"}])
        )

        entries = load_suite_entries("my_suite")

        assert entries[1]["query"] == "q1"
        assert entries[2]["query"] == "q2"

    def test_missing_file_returns_empty(self, suites_dir):
        assert load_suite_entries("nope") == {}

    def test_malformed_file_returns_empty(self, suites_dir):
        (suites_dir / "bad.json").write_text("{not json")

        assert load_suite_entries("bad") == {}


class TestBuildGoalsReport:
    @pytest.fixture
    def suites_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(common_module, "SUITES_DIR", tmp_path)
        (tmp_path / "my_suite.json").write_text(
            json.dumps(
                [
                    {
                        "id": 1,
                        "difficulty": "easy",
                        "query": "What is the book Dune?",
                        "expected_nodes": ["Retrieve_by_Title"],
                    },
                    {"id": 2, "difficulty": "easy", "query": "Surprise me."},
                ]
            )
        )
        return tmp_path

    def _build(self, rows):
        return build_goals_report(
            rows, git_sha="abc1234", generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
        )

    def test_match_mismatch_and_no_expectations_reported(self, suites_dir):
        rows = [
            make_row(1, goal_types=("Retrieve_by_Title", "Analyze_Summarize")),
            make_row(2, goal_types=("Analyze_Similar_Books",)),
        ]

        report, overall = self._build(rows)

        assert "abc1234" in report
        assert "What is the book Dune?" in report
        assert "mismatch" in report
        assert "Analyze_Summarize" in report  # the extra node is named
        assert overall == {
            "cases": 2,
            "match": 0,
            "mismatch": 1,
            "no_expectations": 1,
        }

    def test_clean_match(self, suites_dir):
        report, overall = self._build([make_row(1, goal_types=("Retrieve_by_Title",))])

        assert overall["match"] == 1
        assert "✅ match" in report

    def test_case_missing_from_json_falls_back_to_recorded_message(self, suites_dir):
        report, overall = self._build([make_row(99, user_message="the recorded query")])

        assert "the recorded query" in report
        assert overall["no_expectations"] == 1

    def test_no_rows_says_so(self, suites_dir):
        report, overall = self._build([])

        assert "No test runs found" in report
        assert overall["cases"] == 0

    def test_says_nothing_about_tokens_or_cost(self, suites_dir):
        # the split is the point: correctness here, spend in report.py
        rows = [
            make_row(
                1,
                goal_types=("Retrieve_by_Title",),
                token_usage={
                    "total": 1100,
                    "prompt": 1000,
                    "completion": 100,
                    "cached": 600,
                    "cost_usd": 0.00042,
                },
            )
        ]

        report, _ = self._build(rows)

        for spend_word in ("token", "cost", "cache", "$"):
            assert spend_word not in report.lower()
