"""Post-process eval-suite runs against their suite JSON expectations.

For every test_runs row (written by evals/run_suites.py) this joins the
chat_runs row it points at, pulls the goal types the run actually accepted
(planner.output.parse_result.accepted_goals[].target_node_type), and diffs
them against the case's expected_nodes in evals/suites/<suite_name>.json:
matched / missing / extra, duplicates counted. Cases whose suite entry
defines no expected_nodes are flagged rather than judged.

By default only the most recent run of each (suite_name, case_id) is
evaluated — pass --all to include every recorded run. The markdown report is
saved to evals/results/eval_<timestamp>.md (override with --output); the
console just gets the summary line and the file path.

Usage (from backend/, or `make suite-eval`):
    poetry run python evals/eval.py
    poetry run python evals/eval.py --suite query_suite --suite query_suite_stress
    poetry run python evals/eval.py --all --output evals/results/my_campaign/eval.md
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUITES_DIR = Path(__file__).parent / "suites"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "results"

QUERY_PRINT_LIMIT = 60


def fetch_rows(suite_names: list[str] | None) -> list[dict]:
    """One dict per test_runs row joined with its chat_runs row (planner
    envelope included — accepted goals live inside it), ordered by
    (suite_name, suite_case_id, run created_at). Thin DB shim — everything
    after this is pure and unit-testable."""
    # imported here so the pure eval helpers stay importable without the
    # backend's DB config (mirrors run_suites.record_test_runs)
    import asyncio

    from sqlalchemy import select

    from config import settings
    from db.async_engine import close_async_engine, get_async_engine, get_session_factory
    from db.schema import ChatRunModel, TestRunModel

    stmt = (
        select(
            TestRunModel.suite_name,
            TestRunModel.suite_case_id,
            TestRunModel.chat_id,
            ChatRunModel.session_id,
            ChatRunModel.created_at,
            ChatRunModel.ok,
            ChatRunModel.runtime_error,
            ChatRunModel.user_message,
            ChatRunModel.planner,
        )
        .join(ChatRunModel, ChatRunModel.chat_id == TestRunModel.chat_id)
        .order_by(
            TestRunModel.suite_name,
            TestRunModel.suite_case_id,
            ChatRunModel.created_at,
        )
    )
    if suite_names:
        stmt = stmt.where(TestRunModel.suite_name.in_(suite_names))

    async def _fetch() -> list[dict]:
        engine = get_async_engine(settings.sqlalchemy)
        try:
            session_factory = get_session_factory(engine)
            async with session_factory() as session:
                result = await session.execute(stmt)
                return [dict(row) for row in result.mappings().all()]
        finally:
            await close_async_engine(engine)

    return asyncio.run(_fetch())


def latest_per_case(rows: list[dict]) -> list[dict]:
    """Keep only the most recent run of each (suite_name, suite_case_id).
    Assumes rows are ordered by created_at within a case (as fetch_rows
    returns them), so the last row wins."""
    latest: dict[tuple, dict] = {}
    for row in rows:
        latest[(row["suite_name"], row["suite_case_id"])] = row
    return list(latest.values())


def load_suite_entries(suite_name: str) -> dict[int, dict]:
    """{case_id: entry} from evals/suites/<suite_name>.json; {} when the
    file is missing or malformed — those cases are then evaluated as having
    no expectations and fall back to the recorded user_message."""
    path = SUITES_DIR / f"{suite_name}.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        print(f"WARNING: could not read suite file {path}", file=sys.stderr)
        return {}
    if not isinstance(entries, list):
        print(f"WARNING: suite file {path} is not a list of entries", file=sys.stderr)
        return {}
    return {
        entry["id"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), int)
    }


def accepted_goal_types(planner: Any) -> list[str]:
    """target_node_type of each accepted goal in a recorded planner envelope
    (the chat_runs.planner JSONB dict). [] when the run has no parse result,
    e.g. it errored before parsing finished."""
    if not isinstance(planner, dict):
        return []
    output = planner.get("output")
    parse_result = output.get("parse_result") if isinstance(output, dict) else None
    goals = parse_result.get("accepted_goals") if isinstance(parse_result, dict) else None
    if not isinstance(goals, list):
        return []
    return [
        goal["target_node_type"]
        for goal in goals
        if isinstance(goal, dict) and isinstance(goal.get("target_node_type"), str)
    ]


def diff_node_types(
    expected: list[str] | None, actual: list[str]
) -> dict[str, list[str]] | None:
    """Multiset diff of a case's expected_nodes against the goal types a run
    actually accepted — duplicates count, so expecting Retrieve_by_Title
    twice and producing it once leaves one missing. None (not an empty diff)
    when the case defines no expectations."""
    if expected is None:
        return None
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    return {
        "matched": sorted((expected_counts & actual_counts).elements()),
        "missing": sorted((expected_counts - actual_counts).elements()),
        "extra": sorted((actual_counts - expected_counts).elements()),
    }


def evaluate_row(row: dict, entry: dict) -> dict:
    """One case's verdict: the diff plus a status —
    'match' (all expected nodes accepted, nothing extra), 'mismatch',
    or 'no_expectations' (the suite entry defines no expected_nodes)."""
    expected = entry.get("expected_nodes")
    if not isinstance(expected, list):
        expected = None
    diff = diff_node_types(expected, accepted_goal_types(row.get("planner")))
    if diff is None:
        status = "no_expectations"
    elif not diff["missing"] and not diff["extra"]:
        status = "match"
    else:
        status = "mismatch"
    return {"status": status, "expected": expected, "diff": diff}


def summarize(verdicts: list[dict]) -> dict:
    counts = Counter(v["status"] for v in verdicts)
    return {
        "cases": len(verdicts),
        "match": counts["match"],
        "mismatch": counts["mismatch"],
        "no_expectations": counts["no_expectations"],
    }


def _truncate(text: str, limit: int = QUERY_PRINT_LIMIT) -> str:
    text = " ".join(text.split())  # markdown tables can't hold newlines
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _summary_line(stats: dict) -> str:
    return (
        f"{stats['match']}/{stats['match'] + stats['mismatch']} matched"
        f" ({stats['mismatch']} mismatched, "
        f"{stats['no_expectations']} without expectations, "
        f"{stats['cases']} cases total)"
    )


_STATUS_ICON = {"match": "✅", "mismatch": "❌", "no_expectations": "⚠️"}


def build_eval_report(rows: list[dict], git_sha: str, generated_at: datetime) -> tuple[str, dict]:
    """Markdown report over the given (already latest-filtered, if desired)
    joined rows, plus the overall stats dict for the console summary."""
    suites: dict[str, list[dict]] = {}
    for row in rows:
        suites.setdefault(row["suite_name"], []).append(row)

    lines = [
        "# Eval suite node-expectation report",
        "",
        f"- generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- commit: `{git_sha}`",
        f"- suites: {', '.join(sorted(suites)) if suites else 'none'}",
        "",
    ]

    if not rows:
        lines.append("_No test runs found — run an eval suite first (make query-suite)._")
        return "\n".join(lines) + "\n", summarize([])

    all_verdicts: list[dict] = []
    suite_sections: list[str] = []

    for suite_name in sorted(suites):
        suite_rows = sorted(suites[suite_name], key=lambda r: r["suite_case_id"])
        entries = load_suite_entries(suite_name)

        verdicts = []
        section = [
            f"### `{suite_name}`",
            "",
            "| case | difficulty | query | result | missing | extra | run ok | chat_id |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in suite_rows:
            entry = entries.get(row["suite_case_id"], {})
            verdict = evaluate_row(row, entry)
            verdicts.append(verdict)

            diff = verdict["diff"]
            query = entry.get("query") or row.get("user_message") or ""
            run_ok = {True: "✅", False: "❌"}.get(row["ok"], "❔")
            if row["runtime_error"]:
                run_ok += f" {row['runtime_error']}"
            section.append(
                f"| {row['suite_case_id']} "
                f"| {entry.get('difficulty') or '—'} "
                f"| {_truncate(query)} "
                f"| {_STATUS_ICON[verdict['status']]} {verdict['status']} "
                f"| {', '.join(diff['missing']) if diff and diff['missing'] else '—'} "
                f"| {', '.join(diff['extra']) if diff and diff['extra'] else '—'} "
                f"| {run_ok} "
                f"| `{row['chat_id']}` |"
            )
        section += ["", f"**{suite_name}:** {_summary_line(summarize(verdicts))}", ""]

        all_verdicts += verdicts
        suite_sections += section

    overall = summarize(all_verdicts)
    lines += [f"**Overall:** {_summary_line(overall)}", ""]
    lines += suite_sections

    return "\n".join(lines) + "\n", overall


def current_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        action="append",
        help="Only evaluate this suite (file stem, e.g. query_suite); repeatable.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include every recorded run, not just the latest per case.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Where to save the report (default: evals/results/eval_<timestamp>.md).",
    )
    args = parser.parse_args()

    rows = fetch_rows(args.suite)
    if not args.all:
        rows = latest_per_case(rows)

    generated_at = datetime.now(timezone.utc)
    report, overall = build_eval_report(rows, current_git_sha(), generated_at)

    output = args.output or (
        DEFAULT_OUTPUT_DIR / f"eval_{generated_at.strftime('%Y%m%d_%H%M%S')}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)

    print(f"Overall: {_summary_line(overall)}")
    print(f"report saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
