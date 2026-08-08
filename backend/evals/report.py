"""What eval-suite runs *cost* — tokens, dollars, latency, failures.

Joins test_runs (written by evals/run_suites.py) with chat_runs and enriches
each row with the case's details from its suite JSON (query, difficulty,
note). No expectations are checked here — whether the planner picked the right
nodes is report_system_goals.py's job. This report answers the operational
question instead: did it run, how long did it take, how many tokens, split
across which models, and what did it cost.

Dollar figures come from `cost_usd`, stamped onto each run's token_usage at
the time it was recorded (see airglider/src/config.py). Runs recorded before cost
tracking landed have no `cost_usd` and are counted as unpriced rather than
free — the summary says how many, so a total is never quietly understated.

By default only the most recent run of each (suite_name, case_id) is
reported — pass --all to include every recorded run.

Usage (from backend/, or `make suite-report`):
    poetry run python evals/report.py
    poetry run python evals/report.py --suite query_suite --suite query_suite_stress
    poetry run python evals/report.py --all --output evals/results/my_campaign/report.md
"""

import sys
from datetime import datetime, timezone

from evals.common import (
    build_arg_parser,
    current_git_sha,
    fetch_rows,
    group_by_suite,
    latest_per_case,
    load_suite_entries,
    report_header,
    truncate,
)

QUERY_PRINT_LIMIT = 80


def token_counts(token_usage) -> dict:
    """prompt/cached/cost from a row's token_usage (selected out of the planner
    JSONB). Zeros for anything absent — rows recorded before the cached field
    existed simply count as uncached.

    `cost_usd` is None, not 0.0, when the run predates cost tracking: unknown
    spend must not be averaged in as free spend.
    """
    usage = token_usage if isinstance(token_usage, dict) else {}
    prompt = usage.get("prompt")
    cached = usage.get("cached")
    cost = usage.get("cost_usd")
    return {
        "prompt": prompt if isinstance(prompt, int) else 0,
        "cached": cached if isinstance(cached, int) else 0,
        "cost_usd": float(cost) if isinstance(cost, (int, float)) else None,
    }


def unpriced_models(rows: list[dict]) -> list[str]:
    """Models that contributed tokens but had no rate when the run was
    recorded, so their spend is missing from every cost figure here.

    This is the failure mode a cost report must never hide: those runs still
    carry a `cost_usd`, it is just too low, so counting priced-vs-unpriced
    *runs* would not catch it.
    """
    found: set[str] = set()
    for row in rows:
        usage = row.get("token_usage")
        models = usage.get("unpriced_models") if isinstance(usage, dict) else None
        if isinstance(models, list):
            found.update(m for m in models if isinstance(m, str))
    return sorted(found)


def spend_by_model(rows: list[dict]) -> dict[str, dict]:
    """{model: summed counts} across the given runs, from each token_usage's
    per-model split. Empty when no run carries one."""
    totals: dict[str, dict] = {}
    for row in rows:
        usage = row.get("token_usage")
        by_model = usage.get("by_model") if isinstance(usage, dict) else None
        if not isinstance(by_model, dict):
            continue
        for model, counts in by_model.items():
            if not isinstance(counts, dict):
                continue
            bucket = totals.setdefault(
                model, {"total": 0, "prompt": 0, "cached": 0, "completion": 0}
            )
            for key in bucket:
                value = counts.get(key)
                if isinstance(value, int):
                    bucket[key] += value
    return totals


def summarize(rows: list[dict]) -> dict:
    """Outcome, token, cost and latency stats over a set of reported runs.
    The cache hit rate is recomputed from the summed counts — per-run rates
    don't add. `unpriced` counts runs with no cost recorded, so a small
    total_cost_usd can be read as 'cheap' or 'incomplete' correctly."""
    durations = [r["duration_s"] for r in rows if r["duration_s"] is not None]
    tokens = [r["total_tokens"] for r in rows if r["total_tokens"] is not None]
    counts = [token_counts(r.get("token_usage")) for r in rows]
    prompt = sum(c["prompt"] for c in counts)
    cached = sum(c["cached"] for c in counts)
    costs = [c["cost_usd"] for c in counts if c["cost_usd"] is not None]
    return {
        "cases": len(rows),
        "ok": sum(1 for r in rows if r["ok"] is True),
        "failed": sum(1 for r in rows if r["ok"] is False),
        "runtime_errors": sum(1 for r in rows if r["runtime_error"]),
        "total_tokens": sum(tokens),
        "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else 0,
        "cached_tokens": cached,
        "cache_hit_rate": cached / prompt if prompt else 0.0,
        "total_cost_usd": round(sum(costs), 6) if costs else 0.0,
        "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else 0.0,
        "unpriced": len(counts) - len(costs),
        "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
    }


def _summary_table(title: str, stats: dict) -> list[str]:
    unpriced = f" ({stats['unpriced']} unpriced)" if stats["unpriced"] else ""
    return [
        f"### {title}",
        "",
        "| cases | ok | failed | runtime errors | total tokens | avg tokens "
        "| cached tokens | cache hit | total cost | avg cost | avg duration |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        (
            f"| {stats['cases']} | {stats['ok']} | {stats['failed']} "
            f"| {stats['runtime_errors']} | {stats['total_tokens']} "
            f"| {stats['avg_tokens']} | {stats['cached_tokens']} "
            f"| {stats['cache_hit_rate']:.1%} "
            f"| ${stats['total_cost_usd']:.4f}{unpriced} "
            f"| ${stats['avg_cost_usd']:.6f} "
            f"| {stats['avg_duration_s']}s |"
        ),
        "",
    ]


def _model_table(totals: dict[str, dict]) -> list[str]:
    if not totals:
        return []
    lines = [
        "### Spend by model",
        "",
        "| model | tokens | prompt | cached | completion | cache hit |",
        "|---|---|---|---|---|---|",
    ]
    for model, counts in sorted(totals.items(), key=lambda kv: -kv[1]["total"]):
        hit = counts["cached"] / counts["prompt"] if counts["prompt"] else 0.0
        lines.append(
            f"| `{model}` | {counts['total']:,} | {counts['prompt']:,} "
            f"| {counts['cached']:,} | {counts['completion']:,} | {hit:.1%} |"
        )
    lines.append("")
    return lines


def build_report(rows: list[dict], git_sha: str, generated_at: datetime) -> str:
    """Markdown report over the given (already latest-filtered, if desired)
    joined rows. Suite JSON details are looked up per suite; a case missing
    from its JSON falls back to the run's recorded user_message."""
    suites = group_by_suite(rows)
    lines = report_header("Eval suite cost report", suites, git_sha, generated_at)

    if not rows:
        lines.append("_No test runs found — run an eval suite first (make query-suite)._")
        return "\n".join(lines) + "\n"

    lines += _summary_table("Overall", summarize(rows))

    missing = unpriced_models(rows)
    if missing:
        named = ", ".join(f"`{m}`" for m in missing)
        lines += [
            f"> ⚠️ **Costs below are understated.** No rate for {named} when these "
            "runs were recorded, so their tokens are counted but their spend is "
            "not. Add them to `airglider/src/config.py` — re-running this report will "
            "not backfill it, since `cost_usd` is frozen at record time.",
            "",
        ]

    lines += _model_table(spend_by_model(rows))

    for suite_name, suite_rows in sorted(suites.items()):
        entries = load_suite_entries(suite_name)

        lines += _summary_table(f"`{suite_name}`", summarize(suite_rows))
        lines += [
            "| case | difficulty | query | ok | error | duration | tokens | cached "
            "| cost | chat_id | session |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in suite_rows:
            entry = entries.get(row["suite_case_id"], {})
            query = entry.get("query") or row.get("user_message") or ""
            note = entry.get("note")
            ok = {True: "✅", False: "❌"}.get(row["ok"], "❔")
            duration = f"{row['duration_s']:.1f}s" if row["duration_s"] is not None else "—"
            counts = token_counts(row.get("token_usage"))
            cached = f"{counts['cached']}" if counts["prompt"] else "—"
            cost = f"${counts['cost_usd']:.6f}" if counts["cost_usd"] is not None else "—"
            lines.append(
                f"| {row['suite_case_id']} "
                f"| {entry.get('difficulty') or '—'} "
                f"| {truncate(query, QUERY_PRINT_LIMIT)} "
                f"| {ok} "
                f"| {row['runtime_error'] or '—'} "
                f"| {duration} "
                f"| {row['total_tokens'] if row['total_tokens'] is not None else '—'} "
                f"| {cached} "
                f"| {cost} "
                f"| `{row['chat_id']}` "
                f"| `{row['session_id']}` |"
            )
            if note:
                # notes ride along as a quiet extra row under their case
                lines.append(
                    f"| | | _{truncate(note, QUERY_PRINT_LIMIT)}_ | | | | | | | | |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = build_arg_parser(
        description=__doc__,
        output_help="Also write the report to this file "
        "(e.g. evals/results/<campaign>/report.md).",
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
