"""Generate a regression report for eval-suite runs.

Joins test_runs (written by evals/run_suites.py) with chat_runs and enriches
each row with the case's details from its suite JSON (query, difficulty,
note). By default only the most recent run of each (suite_name, case_id) is
reported — pass --all to include every recorded run. No expectations are
checked; this is a plain outcome report: ok/failed, runtime errors, duration
and token stats (cached prompt tokens and cache hit rate included).

Usage (from backend/, or `make suite-report`):
    poetry run python evals/report.py
    poetry run python evals/report.py --suite query_suite --suite query_suite_stress
    poetry run python evals/report.py --all --output evals/results/my_campaign/report.md
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SUITES_DIR = Path(__file__).parent / "suites"

QUERY_PRINT_LIMIT = 80


def fetch_rows(suite_names: list[str] | None) -> list[dict]:
    """One dict per test_runs row joined with its chat_runs row, ordered by
    (suite_name, suite_case_id, run created_at). Thin DB shim — everything
    after this is pure and unit-testable."""
    # imported here so the pure report helpers stay importable without the
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
            ChatRunModel.duration_s,
            ChatRunModel.total_tokens,
            # just the token_usage object, not the whole planner envelope —
            # cached-token counts live only in the JSONB, not in a column
            # (explicit -> instead of subscript: works on any PG version)
            ChatRunModel.planner.op("->")("token_usage").label("token_usage"),
            ChatRunModel.user_message,
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
    file is missing or malformed — reported cases then fall back to the
    recorded user_message and show no difficulty/note."""
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


def token_counts(token_usage) -> dict[str, int]:
    """prompt/cached counts from a row's token_usage (selected out of the
    planner JSONB). Zeros for anything absent — rows recorded before the
    cached field existed simply count as uncached."""
    usage = token_usage if isinstance(token_usage, dict) else {}
    prompt = usage.get("prompt")
    cached = usage.get("cached")
    return {
        "prompt": prompt if isinstance(prompt, int) else 0,
        "cached": cached if isinstance(cached, int) else 0,
    }


def summarize(rows: list[dict]) -> dict:
    """Basic outcome stats over a set of reported runs. The cache hit rate
    is recomputed from the summed counts — per-run rates don't add."""
    durations = [r["duration_s"] for r in rows if r["duration_s"] is not None]
    tokens = [r["total_tokens"] for r in rows if r["total_tokens"] is not None]
    counts = [token_counts(r.get("token_usage")) for r in rows]
    prompt = sum(c["prompt"] for c in counts)
    cached = sum(c["cached"] for c in counts)
    return {
        "cases": len(rows),
        "ok": sum(1 for r in rows if r["ok"] is True),
        "failed": sum(1 for r in rows if r["ok"] is False),
        "runtime_errors": sum(1 for r in rows if r["runtime_error"]),
        "total_tokens": sum(tokens),
        "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else 0,
        "cached_tokens": cached,
        "cache_hit_rate": cached / prompt if prompt else 0.0,
        "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
    }


def _truncate(text: str, limit: int = QUERY_PRINT_LIMIT) -> str:
    text = " ".join(text.split())  # markdown tables can't hold newlines
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _summary_table(title: str, stats: dict) -> list[str]:
    return [
        f"### {title}",
        "",
        "| cases | ok | failed | runtime errors | total tokens | avg tokens | cached tokens | cache hit | avg duration |",
        "|---|---|---|---|---|---|---|---|---|",
        (
            f"| {stats['cases']} | {stats['ok']} | {stats['failed']} "
            f"| {stats['runtime_errors']} | {stats['total_tokens']} "
            f"| {stats['avg_tokens']} | {stats['cached_tokens']} "
            f"| {stats['cache_hit_rate']:.1%} | {stats['avg_duration_s']}s |"
        ),
        "",
    ]


def build_report(rows: list[dict], git_sha: str, generated_at: datetime) -> str:
    """Markdown report over the given (already latest-filtered, if desired)
    joined rows. Suite JSON details are looked up per suite; a case missing
    from its JSON falls back to the run's recorded user_message."""
    suites: dict[str, list[dict]] = {}
    for row in rows:
        suites.setdefault(row["suite_name"], []).append(row)

    lines = [
        "# Eval suite report",
        "",
        f"- generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- commit: `{git_sha}`",
        f"- suites: {', '.join(sorted(suites)) if suites else 'none'}",
        "",
    ]

    if not rows:
        lines.append("_No test runs found — run an eval suite first (make query-suite)._")
        return "\n".join(lines) + "\n"

    lines += _summary_table("Overall", summarize(rows))

    for suite_name in sorted(suites):
        suite_rows = sorted(suites[suite_name], key=lambda r: r["suite_case_id"])
        entries = load_suite_entries(suite_name)

        lines += _summary_table(f"`{suite_name}`", summarize(suite_rows))
        lines += [
            "| case | difficulty | query | ok | error | duration | tokens | cached | chat_id | session |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in suite_rows:
            entry = entries.get(row["suite_case_id"], {})
            query = entry.get("query") or row.get("user_message") or ""
            note = entry.get("note")
            ok = {True: "✅", False: "❌"}.get(row["ok"], "❔")
            duration = f"{row['duration_s']:.1f}s" if row["duration_s"] is not None else "—"
            counts = token_counts(row.get("token_usage"))
            cached = f"{counts['cached']}" if counts["prompt"] else "—"
            lines.append(
                f"| {row['suite_case_id']} "
                f"| {entry.get('difficulty') or '—'} "
                f"| {_truncate(query)} "
                f"| {ok} "
                f"| {row['runtime_error'] or '—'} "
                f"| {duration} "
                f"| {row['total_tokens'] if row['total_tokens'] is not None else '—'} "
                f"| {cached} "
                f"| `{row['chat_id']}` "
                f"| `{row['session_id']}` |"
            )
            if note:
                # notes ride along as a quiet extra row under their case
                lines.append(f"| | | _{_truncate(note)}_ | | | | | | | |")
        lines.append("")

    return "\n".join(lines) + "\n"


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
        help="Only report this suite (file stem, e.g. query_suite); repeatable.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include every recorded run, not just the latest per case.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the report to this file (e.g. evals/results/<campaign>/report.md).",
    )
    args = parser.parse_args()

    rows = fetch_rows(args.suite)
    if not args.all:
        rows = latest_per_case(rows)

    report = build_report(rows, current_git_sha(), datetime.now(timezone.utc))
    print(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
