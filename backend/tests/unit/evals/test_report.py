"""Tests for the cost report's pure parts: outcome/token/cost/latency stats,
the per-model spend split, and the rendered markdown. The DB shim (fetch_rows)
is deliberately thin and not covered here.

Node-expectation checking lives in report_system_goals.py and is tested in
test_report_system_goals.py.
"""

import json
from datetime import datetime, timezone

import pytest

import evals.common as common_module
from evals.common import latest_per_case, load_suite_entries
from evals.report import build_report, spend_by_model, summarize, token_counts


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
        "token_usage": {"total": 100, "prompt": 80, "completion": 20, "cached": 0},
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


class TestTokenCounts:
    def test_extracts_prompt_cached_and_cost(self):
        usage = {"prompt": 80, "cached": 60, "cost_usd": 0.00042}

        assert token_counts(usage) == {
            "prompt": 80,
            "cached": 60,
            "cost_usd": 0.00042,
        }

    def test_row_without_cached_field_counts_as_uncached(self):
        # rows recorded before TokenUsage grew the cached field
        assert token_counts({"total": 100, "prompt": 80})["cached"] == 0

    def test_run_without_cost_is_none_not_zero(self):
        # predates cost tracking — unknown spend, not free spend
        assert token_counts({"prompt": 80})["cost_usd"] is None

    def test_missing_or_malformed_is_all_zeros(self):
        zeros = {"prompt": 0, "cached": 0, "cost_usd": None}
        assert token_counts(None) == zeros
        assert token_counts("not a dict") == zeros
        assert token_counts({"prompt": "NaN"}) == zeros


class TestSpendByModel:
    def test_sums_each_model_across_runs(self):
        rows = [
            make_row(
                1,
                token_usage={
                    "by_model": {
                        "gpt-4.1-mini": {
                            "total": 100,
                            "prompt": 80,
                            "cached": 40,
                            "completion": 20,
                        }
                    }
                },
            ),
            make_row(
                2,
                token_usage={
                    "by_model": {
                        "gpt-4.1-mini": {
                            "total": 50,
                            "prompt": 40,
                            "cached": 0,
                            "completion": 10,
                        },
                        "gpt-5-nano": {
                            "total": 30,
                            "prompt": 25,
                            "cached": 5,
                            "completion": 5,
                        },
                    }
                },
            ),
        ]

        totals = spend_by_model(rows)

        assert totals["gpt-4.1-mini"] == {
            "total": 150,
            "prompt": 120,
            "cached": 40,
            "completion": 30,
        }
        assert totals["gpt-5-nano"]["total"] == 30

    def test_runs_without_a_split_are_skipped(self):
        assert spend_by_model([make_row(1, token_usage=None)]) == {}
        assert spend_by_model([make_row(1, token_usage={"by_model": "nope"})]) == {}


class TestSummarize:
    def test_counts_and_averages(self):
        rows = [
            make_row(1, duration_s=2.0, total_tokens=100),
            make_row(2, ok=False, runtime_error="StepFailure", duration_s=6.0, total_tokens=300),
            make_row(3, ok=None, duration_s=None, total_tokens=None, token_usage=None),
        ]

        stats = summarize(rows)

        assert stats == {
            "cases": 3,
            "ok": 1,
            "failed": 1,
            "runtime_errors": 1,
            "total_tokens": 400,
            "avg_tokens": 200,
            "cached_tokens": 0,
            "cache_hit_rate": 0.0,
            "total_cost_usd": 0.0,
            "avg_cost_usd": 0.0,
            "unpriced": 3,
            "avg_duration_s": 4.0,
        }

    def test_cache_hit_rate_from_summed_counts(self):
        # per-run rates are 1.0 and 0.0 — the aggregate must come from the
        # summed counts (0.5), not an average of rates
        rows = [
            make_row(1, token_usage={"prompt": 100, "cached": 100}),
            make_row(2, token_usage={"prompt": 100, "cached": 0}),
        ]

        stats = summarize(rows)

        assert stats["cached_tokens"] == 100
        assert stats["cache_hit_rate"] == 0.5

    def test_cost_sums_across_runs(self):
        rows = [
            make_row(1, token_usage={"prompt": 100, "cost_usd": 0.001}),
            make_row(2, token_usage={"prompt": 100, "cost_usd": 0.002}),
        ]

        stats = summarize(rows)

        assert stats["total_cost_usd"] == 0.003
        assert stats["avg_cost_usd"] == 0.0015
        assert stats["unpriced"] == 0

    def test_unpriced_runs_are_counted_not_averaged_as_free(self):
        # averaging a missing cost as 0.0 would halve the real average
        rows = [
            make_row(1, token_usage={"prompt": 100, "cost_usd": 0.002}),
            make_row(2, token_usage={"prompt": 100}),
        ]

        stats = summarize(rows)

        assert stats["total_cost_usd"] == 0.002
        assert stats["avg_cost_usd"] == 0.002
        assert stats["unpriced"] == 1

    def test_empty_rows(self):
        stats = summarize([])

        assert stats["cases"] == 0
        assert stats["avg_tokens"] == 0
        assert stats["cache_hit_rate"] == 0.0
        assert stats["total_cost_usd"] == 0.0
        assert stats["avg_duration_s"] == 0.0


class TestBuildReport:
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

    def test_cached_tokens_and_hit_rate_shown(self, suites_dir):
        out = self._build(
            [make_row(1, token_usage={"total": 100, "prompt": 80, "cached": 60})]
        )

        assert "| 100 | 60 " in out  # per-case tokens | cached cells
        assert "75.0%" in out  # summary cache hit rate

    def test_row_without_token_usage_renders_dash(self, suites_dir):
        out = self._build([make_row(1, token_usage=None)])

        assert "| 100 | — " in out
        assert "0.0%" in out

    def test_cost_shown_per_case_and_in_summary(self, suites_dir):
        out = self._build(
            [make_row(1, token_usage={"total": 100, "prompt": 80, "cost_usd": 0.001234})]
        )

        assert "$0.001234" in out  # per-case cost cell
        assert "$0.0012" in out  # summary total

    def test_unpriced_runs_are_flagged_in_the_summary(self, suites_dir):
        out = self._build([make_row(1, token_usage={"prompt": 80})])

        assert "1 unpriced" in out

    def test_spend_by_model_section(self, suites_dir):
        out = self._build(
            [
                make_row(
                    1,
                    token_usage={
                        "prompt": 80,
                        "by_model": {
                            "gpt-4.1-mini": {
                                "total": 100,
                                "prompt": 80,
                                "cached": 40,
                                "completion": 20,
                            }
                        },
                    },
                )
            ]
        )

        assert "Spend by model" in out
        assert "`gpt-4.1-mini`" in out

    def test_no_model_split_omits_the_section(self, suites_dir):
        out = self._build([make_row(1)])

        assert "Spend by model" not in out
