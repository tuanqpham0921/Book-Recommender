"""Send a suite of queries to the backend one after another.

Queries are loaded from tests/query_suite.json (override with --suite).
Each query is POSTed to /session/{id}/message and its SSE stream is
consumed to completion before the next query is sent.

Usage (from backend/):
    poetry run python tests/scripts/run_query_suites.py
    poetry run python tests/scripts/run_query_suites.py --difficulty easy
    poetry run python tests/scripts/run_query_suites.py --ids 1 16 50
    poetry run python tests/scripts/run_query_suites.py --new-session-per-query
    poetry run python tests/scripts/run_query_suites.py --suite /home/tuani/Book-Recommender/backend/playground/app_mock/query_suite_extended.json
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

DEFAULT_SUITE_PATH = Path(__file__).parent.parent / "query_suite.json"

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


def send_query(client: httpx.Client, session_id: str, message: str) -> None:
    started = time.monotonic()
    event_count = 0
    content_parts: list[str] = []

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
            elif event.get("type") == "content.delta":
                content_parts.append(str(event.get("data", "")))
            else:
                print(f"  [{event.get('type', '?')}] {str(event)}")

    if content_parts:
        print("  --- response ---")
        print("  " + "".join(content_parts).replace("\n", "\n  "))

    duration = time.monotonic() - started
    print(f"  done: {event_count} events in {duration:.1f}s")


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
    args = parser.parse_args()

    entries = load_suite(args.suite, args.difficulty, args.ids)
    if not entries:
        print("No queries matched the given filters.", file=sys.stderr)
        return 1
    print(f"loaded {len(entries)} queries from {args.suite}")

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
                send_query(client, session_id, entry["query"])
            except httpx.HTTPError as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                # return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
