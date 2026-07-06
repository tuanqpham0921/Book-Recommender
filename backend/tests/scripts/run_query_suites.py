"""Send a suite of queries to the backend one after another.

Each query is POSTed to /session/{id}/message and its SSE stream is
consumed to completion before the next query is sent.

Usage (from backend/):
    poetry run python tests/scripts/run_query_suites.py
    poetry run python tests/scripts/run_query_suites.py --base-url http://localhost:8000
    poetry run python tests/scripts/run_query_suites.py --new-session-per-query
"""

import argparse
import json
import sys
import time

import httpx

QUERIES = [
    "Recommend me a book similar to Dune.",
    "Compare The Hobbit and The Lord of the Rings.",
    "Find the book with ISBN 9780439023481.",
    "I like slow-burn literary fiction with unreliable narrators, any suggestions?",
]

STREAM_TIMEOUT_SECONDS = 300.0
EVENT_PRINT_LIMIT = 200


def truncate(text: str, limit: int = EVENT_PRINT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (truncated, {len(text)} chars total)"


def create_session(client: httpx.Client) -> str:
    response = client.post("/session/new")
    response.raise_for_status()
    session_id = response.json()["id"]
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
        "--new-session-per-query",
        action="store_true",
        help="Create a fresh session for every query instead of reusing one.",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url) as client:
        session_id = None
        for i, query in enumerate(QUERIES, start=1):
            if session_id is None or args.new_session_per_query:
                session_id = create_session(client)

            print(f"\n--- query {i}/{len(QUERIES)}: {query}")
            try:
                send_query(client, session_id, query)
            except httpx.HTTPError as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
