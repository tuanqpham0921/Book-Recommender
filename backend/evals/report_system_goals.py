"""Check what the planner *decided* against what each suite case expects.

For every test_runs row (written by evals/run_suites.py) this joins the
chat_runs row it points at, pulls the goal types the run actually accepted
(planner.output.parse_result.accepted_goals[].target_node_type), and diffs
them against the case's expected_nodes in evals/suites/<suite_name>.json:
matched / missing / extra, duplicates counted. Cases whose suite entry
defines no expected_nodes are flagged rather than judged.

This is the project's golden test — correctness only. Cost, tokens and
latency are deliberately *not* reported here; that is report.py's job.

By default only the most recent run of each (suite_name, case_id) is
evaluated — pass --all to include every recorded run. The markdown report is
saved to evals/results/system_goals_<timestamp>.md (override with --output);
the console just gets the summary line and the file path.

Usage (from backend/, or `make suite-goals`):
    poetry run python evals/report_system_goals.py
    poetry run python evals/report_system_goals.py --suite query_suite --suite query_suite_stress
    poetry run python evals/report_system_goals.py --all --output evals/results/my_campaign/system_goals.md
"""

import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from evals.common import (
    DEFAULT_OUTPUT_DIR,
    build_arg_parser,
    current_git_sha,
    fetch_rows,
    group_by_suite,
    latest_per_case,
    load_suite_entries,
    report_header,
    truncate,
)

QUERY_PRINT_LIMIT = 60

_STATUS_ICON = {"match": "✅", "mismatch": "❌", "no_expectations": "⚠️"}


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


def _summary_line(stats: dict) -> str:
    return (
        f"{stats['match']}/{stats['match'] + stats['mismatch']} matched"
        f" ({stats['mismatch']} mismatched, "
        f"{stats['no_expectations']} without expectations, "
        f"{stats['cases']} cases total)"
    )


def build_goals_report(
    rows: list[dict], git_sha: str, generated_at: datetime
) -> tuple[str, dict]:
    """Markdown report over the given (already latest-filtered, if desired)
    joined rows, plus the overall stats dict for the console summary."""
    suites = group_by_suite(rows)
    lines = report_header(
        "Eval suite system-goals report", suites, git_sha, generated_at
    )

    if not rows:
        lines.append("_No test runs found — run an eval suite first (make query-suite)._")
        return "\n".join(lines) + "\n", summarize([])

    all_verdicts: list[dict] = []
    suite_sections: list[str] = []

    for suite_name, suite_rows in sorted(suites.items()):
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
                f"| {truncate(query, QUERY_PRINT_LIMIT)} "
                f"| {_STATUS_ICON[verdict['status']]} {verdict['status']} "
                f"| {', '.join(diff['missing']) if diff and diff['missing'] else '—'} "
                f"| {', '.join(diff['extra']) if diff and diff['extra'] else '—'} "
                f"| {run_ok} "
                f"| `{row['chat_id']}` |"
            )
        section += [
            "",
            f"**{suite_name}:** {_summary_line(summarize(verdicts))}",
            "",
        ]

        all_verdicts += verdicts
        suite_sections += section

    overall = summarize(all_verdicts)
    lines += [f"**Overall:** {_summary_line(overall)}", ""]
    lines += suite_sections

    return "\n".join(lines) + "\n", overall


def main() -> int:
    parser = build_arg_parser(
        description=__doc__,
        output_help="Where to save the report "
        "(default: evals/results/system_goals_<timestamp>.md).",
    )
    args = parser.parse_args()

    rows = fetch_rows(args.suite, include_planner=True)
    if not args.all:
        rows = latest_per_case(rows)

    generated_at = datetime.now(timezone.utc)
    report, overall = build_goals_report(rows, current_git_sha(), generated_at)

    output = args.output or (
        DEFAULT_OUTPUT_DIR / f"system_goals_{generated_at.strftime('%Y%m%d_%H%M%S')}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)

    print(f"Overall: {_summary_line(overall)}")
    print(f"report saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
