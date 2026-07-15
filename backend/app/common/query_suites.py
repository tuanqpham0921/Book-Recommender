"""Look up query-suite entries (tests/query_suite*.json) by suite name + case id.

Used by the review page to show, next to a recorded suite run, the suite
case that produced it: its note, difficulty, and what the suite expects
(system goal types today, node lists as the legacy shape). The suite files
are test data and are not shipped in deploy images, so every lookup degrades
to None instead of raising when a file is missing or malformed.
"""

import json
import logging
import re
from functools import lru_cache
from typing import Any

from config import FilesLocationConstants

logger = logging.getLogger(__name__)

# suite_name is client-supplied (stored on chat_runs rows); confine lookups
# to plain names inside QUERY_SUITES_DIR — no separators, no traversal
_SUITE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@lru_cache(maxsize=16)
def _load_suite_cached(suite_name: str, mtime: float) -> dict[int, dict] | None:
    """Parse one suite file into {case_id: entry}. mtime is part of the key
    purely to invalidate the cache when the file changes on disk."""
    path = FilesLocationConstants.QUERY_SUITES_DIR / f"{suite_name}.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read query suite %s", path)
        return None
    if not isinstance(entries, list):
        logger.warning("Query suite %s is not a list of entries", path)
        return None
    return {
        entry["id"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), int)
    }


def _load_suite(suite_name: str) -> dict[int, dict] | None:
    if not suite_name or not _SUITE_NAME_RE.fullmatch(suite_name):
        return None
    path = FilesLocationConstants.QUERY_SUITES_DIR / f"{suite_name}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return _load_suite_cached(suite_name, mtime)


def _expected_goal_types(entry: dict) -> list[str] | None:
    """Ordered goal types from expected_system_goals, a list of one-key
    {Node_Type: description} dicts. None when the entry doesn't define it."""
    expected = entry.get("expected_system_goals")
    if not isinstance(expected, list):
        return None
    return [
        goal_type
        for goal in expected
        if isinstance(goal, dict)
        for goal_type in goal
    ]


def get_suite_case(suite_name: str | None, case_id: int | None) -> dict[str, Any] | None:
    """Summary of one suite entry for the review page, or None if the suite
    file or the case can't be found. expected_goal_types / expected_nodes are
    None (vs empty) when the suite entry doesn't define them at all — the
    review page uses that to flag cases still missing expectations."""
    if suite_name is None or case_id is None:
        return None
    suite = _load_suite(suite_name)
    entry = suite.get(case_id) if suite else None
    if entry is None:
        return None
    return {
        "id": case_id,
        "suite_name": suite_name,
        "difficulty": entry.get("difficulty"),
        "query": entry.get("query"),
        "note": entry.get("note"),
        "expected_goal_types": _expected_goal_types(entry),
        "expected_nodes": entry.get("expected_nodes"),
    }
