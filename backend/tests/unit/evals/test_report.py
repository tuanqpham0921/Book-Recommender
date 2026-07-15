"""Tests for the eval report generator's pure parts: latest-per-case
filtering, suite-JSON lookup, outcome stats, and the rendered markdown.
The DB shim (fetch_rows) is deliberately thin and not covered here."""

import json
from datetime import datetime, timezone

import pytest

import evals.report as report
from evals.report import build_report, latest_per_case, load_suite_entries, summarize


def make_row(case_id, *, suite_name="my_suite", chat_id=None, created_at=None, **overrides):
    row = {
        "suite_name": suite_name,
        "suite_case_id": case_id,
        "chat_id": chat_id or f"chat_{suite_name}_{case_id}",
        "session_id": "test_abc123",
        "created_at": created_at or datetime(2026, 7, 15, tzinfo=timezone.utc),
        "ok": True,
        "runtime_error": None,
        "duration_s": 4.0,
        "total_tokens": 100,
        "user_message": "recorded message",
    }
    row.update(overrides)
    return row


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
        monkeypatch.setattr(report, "SUITES_DIR", tmp_path)
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


class TestSummarize:
    def test_counts_and_averages(self):
        rows = [
            make_row(1, duration_s=2.0, total_tokens=100),
            make_row(2, ok=False, runtime_error="StepFailure", duration_s=6.0, total_tokens=300),
            make_row(3, ok=None, duration_s=None, total_tokens=None),
        ]

        stats = summarize(rows)

        assert stats == {
            "cases": 3,
            "ok": 1,
            "failed": 1,
            "runtime_errors": 1,
            "total_tokens": 400,
            "avg_tokens": 200,
            "avg_duration_s": 4.0,
        }

    def test_empty_rows(self):
        stats = summarize([])

        assert stats["cases"] == 0
        assert stats["avg_tokens"] == 0
        assert stats["avg_duration_s"] == 0.0


class TestBuildReport:
    @pytest.fixture
    def suites_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(report, "SUITES_DIR", tmp_path)
        (tmp_path / "my_suite.json").write_text(
            json.dumps(
                [
                    {
                        "id": 1,
                        "difficulty": "easy",
                        "query": "What is the book Dune?",
                        "note": "Single title lookup.",
                    }
                ]
            )
        )
        return tmp_path

    def _build(self, rows):
        return build_report(
            rows, git_sha="abc1234", generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
        )

    def test_case_details_come_from_suite_json(self, suites_dir):
        out = self._build([make_row(1)])

        assert "abc1234" in out
        assert "`my_suite`" in out
        assert "What is the book Dune?" in out
        assert "easy" in out
        assert "Single title lookup." in out

    def test_case_missing_from_json_falls_back_to_recorded_message(self, suites_dir):
        out = self._build([make_row(99, user_message="the recorded query")])

        assert "the recorded query" in out

    def test_no_rows_says_so(self, suites_dir):
        out = self._build([])

        assert "No test runs found" in out

    def test_runtime_error_and_failure_shown(self, suites_dir):
        out = self._build([make_row(1, ok=False, runtime_error="StepFailure")])

        assert "StepFailure" in out
        assert "❌" in out
