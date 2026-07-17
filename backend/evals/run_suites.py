"""Send a suite of queries to the backend one after another.

Queries are loaded from evals/suites/query_suite.json (override with --suite).
Each query is POSTed to /session/{id}/message and its SSE stream is
consumed to completion before the next query is sent.

After the run, one test_runs row is written per completed query linking the
chat_runs row (chat_id, captured from the chat.id SSE event) back to its
suite entry (suite_name, suite_case_id) — evals/report.py joins on that to
build the regression report. Skip the DB write with --no-record, e.g. when
the target backend's database isn't reachable from this machine.

Usage (from backend/, or via the make targets in evals/makefile):
    poetry run python evals/run_suites.py
    poetry run python evals/run_suites.py --difficulty easy
    poetry run python evals/run_suites.py --ids 1 16 50
    poetry run python evals/run_suites.py --new-session-per-query
    poetry run python evals/run_suites.py --suite evals/suites/query_suite_extended.json
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

DEFAULT_SUITE_PATH = Path(__file__).parent / "suites" / "query_suite.json"

STREAM_TIMEOUT_SECONDS = 300.0
EVENT_PRINT_LIMIT = 200


def truncate(text: str, limit: int = EVENT_PRINT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (truncated, {len(text)} chars total)"


def load_suite(
    suite_path: Path,
    difficulties: list[str] | None,
    ids: list[int] | None,
) -> list[dict]:
    with suite_path.open() as f:
        entries = json.load(f)

    if difficulties:
        entries = [e for e in entries if e["difficulty"] in difficulties]
    if ids:
        entries = [e for e in entries if e["id"] in ids]
    return entries


def create_session() -> str:
    # minted locally instead of via /session/new: the server would prefix
    # with its own env (dev_ on a local server), but suite runs must always
    # be identifiable as test_ so they can be filtered out of eval queries
    session_id = f"test_{str(uuid.uuid4())[:8]}"
    print(f"session: {session_id}")
    return session_id


def send_query(
    client: httpx.Client,
    session_id: str,
    message: str,
) -> str | None:
    """POST one query and consume its SSE stream to completion. Returns the
    run's chat_id (from the chat.id event, sent first and unconditionally)
    so the caller can link the chat_runs row to its suite entry."""
    started = time.monotonic()
    event_count = 0
    content_parts: list[str] = []
    chat_id: str | None = None

    with client.stream(
        "POST",
        f"/session/{session_id}/message",
        json={"message": message},
        timeout=httpx.Timeout(STREAM_TIMEOUT_SECONDS, connect=10.0),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event_count += 1
            payload = line[len("data:") :].strip()
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                event = None

            if not isinstance(event, dict):
                print(f"  [raw] {payload}")
            elif event.get("type") == "chat.id":
                chat_id = event.get("data", {}).get("chat_id")
                print(f"  [{event.get('type', '?')}] {str(event)}")
            elif event.get("type") == "content.delta":
                content_parts.append(str(event.get("data", "")))
            else:
                print(f"  [{event.get('type', '?')}] {str(event)}")

    if content_parts:
        print("  --- response ---")
        print("  " + "".join(content_parts).replace("\n", "\n  "))

    duration = time.monotonic() - started
    print(f"  done: {event_count} events in {duration:.1f}s")
    return chat_id


def record_test_runs(links: list[dict]) -> None:
    """Insert one test_runs row per completed query, linking its chat_runs
    row to the suite entry that produced it. Each link dict already matches
    TestRunModel columns: chat_id, suite_name, suite_case_id.

    test_runs.chat_id is a real FK, and the backend commits a run's
    chat_runs row just *after* its SSE stream closes — so only chat_ids
    already present in chat_runs are inserted, with one short retry for
    stragglers (in practice only ever the final query of the run)."""
    # imported here, not at module top: plain runs against a remote backend
    # (--no-record) shouldn't require DB config or the backend's dependencies
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from config import settings
    from db.async_engine import close_async_engine, get_async_engine, get_session_factory
    from db.schema import ChatRunModel, TestRunModel

    async def _insert() -> None:
        engine = get_async_engine(settings.sqlalchemy)
        try:
            session_factory = get_session_factory(engine)
            pending = {link["chat_id"]: link for link in links}
            for attempt in (1, 2):
                async with session_factory() as session:
                    result = await session.execute(
                        select(ChatRunModel.chat_id).where(
                            ChatRunModel.chat_id.in_(pending)
                        )
                    )
                    rows = [pending.pop(chat_id) for chat_id in result.scalars()]
                    if rows:
                        await session.execute(
                            pg_insert(TestRunModel)
                            .values(rows)
                            .on_conflict_do_nothing(index_elements=["chat_id"])
                        )
                        await session.commit()
                        print(f"recorded {len(rows)} test_runs rows")
                if not pending or attempt == 2:
                    break
                await asyncio.sleep(2)
            for link in pending.values():
                print(
                    f"  WARNING: no chat_runs row for chat_id={link['chat_id']} "
                    f"({link['suite_name']} #{link['suite_case_id']}) — "
                    "test_runs row skipped",
                    file=sys.stderr,
                )
        finally:
            await close_async_engine(engine)

    asyncio.run(_insert())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--suite",
        type=Path,
        default=DEFAULT_SUITE_PATH,
        help="Path to the query suite JSON file.",
    )
    parser.add_argument(
        "--difficulty",
        action="append",
        choices=["easy", "medium", "hard"],
        help="Only run queries of this difficulty (repeatable).",
    )
    parser.add_argument(
        "--ids",
        type=int,
        nargs="+",
        help="Only run queries with these ids, e.g. --ids 1 16 50.",
    )
    parser.add_argument(
        "--new-session-per-query",
        action="store_true",
        help="Create a fresh session for every query instead of reusing one.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Skip writing test_runs rows to the database after the run.",
    )
    args = parser.parse_args()

    entries = load_suite(args.suite, args.difficulty, args.ids)
    if not entries:
        print("No queries matched the given filters.", file=sys.stderr)
        return 1
    print(f"loaded {len(entries)} queries from {args.suite}")

    links: list[dict] = []
    with httpx.Client(base_url=args.base_url) as client:
        session_id = None
        for i, entry in enumerate(entries, start=1):
            if session_id is None or args.new_session_per_query:
                session_id = create_session()

            print(
                f"\n--- query {i}/{len(entries)} "
                f"(id={entry['id']}, {entry['difficulty']}): {entry['query']}"
            )
            try:
                chat_id = send_query(client, session_id, entry["query"])
            except httpx.HTTPError as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                # return 1
                continue
            if chat_id:
                links.append(
                    {
                        "chat_id": chat_id,
                        "suite_name": args.suite.stem,
                        "suite_case_id": entry["id"],
                    }
                )

    if links and not args.no_record:
        record_test_runs(links)

    return 0


if __name__ == "__main__":
    sys.exit(main())
