"""Shared plumbing for the two eval report generators.

`report_system_goals.py` answers *did the planner pick the right nodes*,
`report.py` answers *what did the run cost*. Both read the same
test_runs ⋈ chat_runs join and the same suite JSONs, so the fetching, filtering
and CLI live here rather than being kept in sync twice.

Everything below the DB shim is pure and unit-testable.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SUITES_DIR = Path(__file__).parent / "suites"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "results"


def fetch_rows(
    suite_names: list[str] | None, *, include_planner: bool = False
) -> list[dict]:
    """One dict per test_runs row joined with its chat_runs row, ordered by
    (suite_name, suite_case_id, created_at).

    `include_planner` pulls the whole planner envelope, which the goals report
    needs for `accepted_goals`. The stats report takes only the `token_usage`
    slice — the envelope is far the heaviest column in the table.
    """
    # imported here so the pure helpers stay importable without the DB config
    import asyncio

    from sqlalchemy import select

    from config import settings
    from db.async_engine import close_async_engine, get_async_engine, get_session_factory
    from db.schema import ChatRunModel, TestRunModel

    columns = [
        TestRunModel.suite_name,
        TestRunModel.suite_case_id,
        TestRunModel.chat_id,
        ChatRunModel.session_id,
        ChatRunModel.created_at,
        ChatRunModel.ok,
        ChatRunModel.runtime_error,
        ChatRunModel.duration_s,
        ChatRunModel.total_tokens,
        ChatRunModel.user_message,
        # explicit -> rather than subscript, for older PG. Cached counts, the
        # per-model split and cost_usd live only in the JSONB.
        ChatRunModel.planner.op("->")("token_usage").label("token_usage"),
    ]
    if include_planner:
        columns.append(ChatRunModel.planner)

    stmt = (
        select(*columns)
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
    Assumes rows are ordered by created_at within a case, so the last wins."""
    latest: dict[tuple, dict] = {}
    for row in rows:
        latest[(row["suite_name"], row["suite_case_id"])] = row
    return list(latest.values())


def group_by_suite(rows: list[dict]) -> dict[str, list[dict]]:
    """{suite_name: rows}, each suite's rows sorted by case id."""
    suites: dict[str, list[dict]] = {}
    for row in rows:
        suites.setdefault(row["suite_name"], []).append(row)
    return {
        name: sorted(suite_rows, key=lambda r: r["suite_case_id"])
        for name, suite_rows in suites.items()
    }


def load_suite_entries(suite_name: str) -> dict[int, dict]:
    """{case_id: entry} from evals/suites/<suite_name>.json; {} when missing or
    malformed, so cases fall back to the recorded user_message."""
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


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())  # markdown tables can't hold newlines
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


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


def build_arg_parser(description: str, output_help: str) -> argparse.ArgumentParser:
    """The CLI both reports share: --suite (repeatable), --all, --output."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--suite",
        action="append",
        help="Only include this suite (file stem, e.g. query_suite); repeatable.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include every recorded run, not just the latest per case.",
    )
    parser.add_argument("--output", type=Path, help=output_help)
    return parser


def report_header(title: str, suites, git_sha: str, generated_at) -> list[str]:
    return [
        f"# {title}",
        "",
        f"- generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- commit: `{git_sha}`",
        f"- suites: {', '.join(sorted(suites)) if suites else 'none'}",
        "",
    ]
