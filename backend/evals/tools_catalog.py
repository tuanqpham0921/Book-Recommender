"""What the planner is told it can do, and what saying it costs.

Every node registered in `app/registry.py` becomes a "tool" the planner LLM
reads about. Its class docstring *is* the tool description — so the catalog is
prompt text that gets billed on every single request, whether or not any of
those tools end up being used. This report inventories it: how many tools,
how many tokens each one's description costs, and what the whole block costs
per request at current rates.

Unlike the other two reports here, this one reads no database — it imports the
live registry, so it always describes the code as it is right now, not a
recorded run. That makes it the thing to re-run after adding or editing a node.

Two separate token costs are reported, because they are paid at different
points by different models:

- **catalog tokens** — `format_node_type_catalog()`, rendered into the goal
  generator and the parse-response prompts (`parse_intent.py`), so the whole
  block is paid twice per request, every request.
- **schema tokens** — the JSON function-tool schema for one node, sent by
  `strategy_classification.py`. Only the nodes an accepted goal targets are
  sent, one per classification call, so this is per-goal, not per-request.

Usage (from backend/, or `make tools-catalog`):
    poetry run python evals/tools_catalog.py
    poetry run python evals/tools_catalog.py --output evals/results/tools_catalog.md
    poetry run python evals/tools_catalog.py --model gpt-4.1-mini
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Must precede the app imports. Running this as a script puts evals/ first on
# sys.path, where common.py then shadows the backend's own `common` package —
# so `app.registry` -> `app.domains.base_request` -> `common.utils` dies with
# "'common' is not a package". The other two reports never import app.*, so
# they never hit it. Putting backend/ ahead of evals/ resolves the collision
# without forcing this to be run as `python -m` from one specific directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tiktoken  # noqa: E402
from openai import pydantic_function_tool  # noqa: E402

from app.registry import (  # noqa: E402
    EXECUTORS_CLS_MAPPING,
    NODE_TYPE_TO_CLS,
    catalog_entries,
    class_docstring,
    format_node_type_catalog,
)
from airglider import PRICES_CHECKED_ON, cost_of  # noqa: E402
from evals.common import current_git_sha, truncate  # noqa: E402

# Long enough for a Purpose: line to survive mostly intact, short enough that
# the numeric columns stay readable beside it (report.py caps queries at 80).
DESCRIPTION_PRINT_LIMIT = 110

# tiktoken 0.9 predates the gpt-4.1/gpt-5 families, so encoding_for_model
# raises KeyError on exactly the models this project uses. o200k_base is the
# encoding those families ship with, so resolve to it rather than guessing.
FALLBACK_ENCODING = "o200k_base"

# The models the planner actually runs, and how many times each sees the whole
# catalog in one request — both call sites are in parse_intent.py:
# _run_llm_args_parse (pinned gpt-4.1) and generate_user_response (BASE_MODEL).
# strategy_classification.py is deliberately absent: it sends per-node schemas,
# not the catalog, and is reported separately.
CATALOG_CONSUMERS = (
    ("gpt-4.1", 1, "parse_intent._run_llm_args_parse (goal generation)"),
    ("gpt-4.1-mini", 1, "parse_intent.generate_user_response (user-facing reply)"),
)

# The sections a node docstring is expected to carry. These are prompt
# engineering, not style: "Do not use" and "Example queries" are the levers for
# the discrimination failures tracked in docs/eval-strategy.md.
EXPECTED_SECTIONS = (
    "Purpose:",
    "Args:",
    "Returns:",
    "depends_on:",
    "Use when:",
    "Do not use:",
    "Constraints:",
)

# A node illustrates itself either with example queries or with example values
# for the field that decides its routing ("Example genres:",
# "Example semantic_input:"). Either satisfies the audit; having neither does
# not.
EXAMPLES_SECTION = re.compile(r"Example [A-Za-z_ ]+:")


def get_encoder(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(FALLBACK_ENCODING)


def count_tokens(text: str, encoder) -> int:
    return len(encoder.encode(text))


def render_catalog_entry(name: str, description: str) -> str:
    """One tool as `format_node_type_catalog` renders it — the name on its own
    line, the description indented under it. Duplicated deliberately rather
    than exported from the registry: this measures what the prompt actually
    contains, so it should break loudly if the renderer changes shape."""
    lines = [name]
    lines += [f"  {line}" if line.strip() else "" for line in description.splitlines()]
    return "\n".join(lines)


def schema_tokens(cls: type, encoder) -> int | None:
    """Tokens for the node's JSON function-tool schema — what
    strategy_classification.py sends per goal. None when the class can't be
    rendered as a tool, which is worth seeing rather than silently zeroing."""
    try:
        tool = pydantic_function_tool(cls, name=cls.__name__)
        return count_tokens(json.dumps(tool), encoder)
    except Exception as e:  # noqa: BLE001 — any failure here is report-worthy
        print(f"WARNING: no tool schema for {cls.__name__}: {e}", file=sys.stderr)
        return None


def missing_sections(description: str) -> list[str]:
    missing = [s for s in EXPECTED_SECTIONS if s not in description]
    if not EXAMPLES_SECTION.search(description):
        missing.append("Example queries:")
    return missing


def purpose_line(description: str) -> str:
    """The docstring's one-line summary — the `Purpose:` section's text, which
    by convention is the first line and the sentence that most determines
    whether the planner reaches for this tool.

    Falls back to the first non-empty line for nodes that don't follow the
    convention, so a malformed docstring still shows *something* here; the
    audit section is what flags it as malformed.
    """
    for line in description.splitlines():
        line = line.strip()
        if line.startswith("Purpose:"):
            return line[len("Purpose:"):].strip()
    for line in description.splitlines():
        if line.strip():
            return line.strip()
    return ""


def table_cell(text: str, limit: int = DESCRIPTION_PRINT_LIMIT) -> str:
    """Squash to one line and cap it. Pipes are escaped first: an unescaped
    one in a docstring would silently split the row into extra columns and
    shift every number after it."""
    return truncate(text.replace("|", "\\|"), limit)


def collect_tools(encoder) -> list[dict]:
    """One row per registered node, in catalog order (which is prompt order)."""
    tools = []
    for tier, section in catalog_entries().items():
        for name, description in section.items():
            cls = NODE_TYPE_TO_CLS[name]
            tools.append(
                {
                    "node_type": name,
                    "tier": tier,
                    "cls": cls.__name__,
                    "tier_short": tier.split(" — ")[0],
                    "purpose": purpose_line(description),
                    "catalog_tokens": count_tokens(
                        render_catalog_entry(name, description), encoder
                    ),
                    "schema_tokens": schema_tokens(cls, encoder),
                    "chars": len(description),
                    "has_executor": cls in EXECUTORS_CLS_MAPPING,
                    "missing_sections": missing_sections(description),
                }
            )
    return tools


def summarize(tools: list[dict], catalog_text: str, encoder) -> dict:
    """Whole-catalog figures. `block_tokens` is the rendered block as sent —
    it exceeds the sum of the per-tool counts by the tier headings and blank
    lines, and it is the number the cost figures use, since that is what the
    prompt is actually charged for."""
    per_tier: dict[str, int] = {}
    for tool in tools:
        per_tier[tool["tier_short"]] = per_tier.get(tool["tier_short"], 0) + 1

    return {
        "tools": len(tools),
        "per_tier": per_tier,
        "block_tokens": count_tokens(catalog_text, encoder),
        "sum_tool_tokens": sum(t["catalog_tokens"] for t in tools),
        "schema_tokens_total": sum(t["schema_tokens"] or 0 for t in tools),
        "no_executor": [t["node_type"] for t in tools if not t["has_executor"]],
        "undocumented": [t["node_type"] for t in tools if t["missing_sections"]],
    }


def prompt_costs(block_tokens: int) -> list[dict]:
    """Per-request cost of shipping the catalog, per consuming call site.

    Both an uncached and a fully-cached figure, because the catalog is the
    most cacheable part of the prompt — it is byte-identical on every request
    — so the cached column is the realistic steady state and the uncached one
    is the cold-start ceiling. The truth is between them; report.py's measured
    cache hit rate says where.
    """
    costs = []
    for model, times, call_site in CATALOG_CONSUMERS:
        tokens = block_tokens * times
        costs.append(
            {
                "model": model,
                "call_site": call_site,
                "tokens": tokens,
                "uncached": cost_of(model, tokens, 0, 0),
                "cached": cost_of(model, tokens, tokens, 0),
            }
        )
    return costs


def _dollars(value: float | None) -> str:
    """Unpriced models render as `?`, never as $0 — the distinction
    airglider/src/config.py draws between unknown spend and free spend."""
    return f"${value:.6f}" if value is not None else "?"


def build_report(git_sha: str, generated_at: datetime, model: str) -> str:
    encoder = get_encoder(model)
    catalog_text = format_node_type_catalog()
    tools = collect_tools(encoder)
    stats = summarize(tools, catalog_text, encoder)

    lines = [
        "# Planner Tool Catalog",
        "",
        f"- generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- commit: `{git_sha}`",
        f"- tokenizer: `{encoder.name}` (via `--model {model}`)",
        f"- rates checked: {PRICES_CHECKED_ON} (`airglider/src/config.py`)",
        "",
        "Read from the live registry, not from a recorded run — this describes "
        "the code as it stands at the commit above.",
        "",
        "## Summary",
        "",
        f"- **{stats['tools']} tools** registered",
    ]
    lines += [
        f"  - {tier}: {count}" for tier, count in sorted(stats["per_tier"].items())
    ]
    lines += [
        f"- **{stats['block_tokens']:,} tokens** in the rendered catalog block "
        f"({stats['sum_tool_tokens']:,} in the tool descriptions themselves, the "
        "rest is tier headings and spacing)",
        f"- **{stats['schema_tokens_total']:,} tokens** if every tool's JSON schema "
        "were sent at once — but classification sends one per accepted goal, so a "
        "typical request pays a small fraction of this",
        "",
    ]

    lines += ["## Cost per request", ""]
    lines += [
        "The catalog is prompt text on every request, used or not. It is "
        "byte-identical each time, so it is the most cache-friendly part of the "
        "prompt — expect the cached column in the steady state and the uncached "
        "one cold.",
        "",
        "| call site | model | tokens | uncached | cached |",
        "|---|---|---:|---:|---:|",
    ]
    total_uncached = 0.0
    total_cached = 0.0
    for cost in prompt_costs(stats["block_tokens"]):
        total_uncached += cost["uncached"] or 0.0
        total_cached += cost["cached"] or 0.0
        lines.append(
            f"| {cost['call_site']} | `{cost['model']}` | {cost['tokens']:,} "
            f"| {_dollars(cost['uncached'])} | {_dollars(cost['cached'])} |"
        )
    lines += [
        f"| **per request** | | | **{_dollars(total_uncached)}** "
        f"| **{_dollars(total_cached)}** |",
        "",
        f"At 1,000 requests: {_dollars(total_uncached * 1000)} uncached, "
        f"{_dollars(total_cached * 1000)} cached — catalog text alone, before "
        "any user message, reasoning or output.",
        "",
    ]

    lines += [
        "## Tools",
        "",
        "`purpose` is the docstring's `Purpose:` line — the sentence that most "
        "decides whether the planner reaches for this tool. `catalog` = tokens "
        "this tool adds to every request. `schema` = tokens its JSON tool "
        "definition costs when classification selects it.",
        "",
        "| node type | class | purpose | tier | catalog | share | schema | executor |",
        "|---|---|---|---|---:|---:|---:|:---:|",
    ]
    for tool in sorted(tools, key=lambda t: -t["catalog_tokens"]):
        share = (
            tool["catalog_tokens"] / stats["block_tokens"] * 100
            if stats["block_tokens"]
            else 0.0
        )
        schema = f"{tool['schema_tokens']:,}" if tool["schema_tokens"] else "—"
        lines.append(
            f"| `{tool['node_type']}` | {tool['cls']} "
            f"| {table_cell(tool['purpose'])} | {tool['tier_short']} "
            f"| {tool['catalog_tokens']:,} | {share:.1f}% | {schema} "
            f"| {'✅' if tool['has_executor'] else '❌'} |"
        )
    lines.append("")

    lines += build_audit(tools, stats)
    return "\n".join(lines)


def build_audit(tools: list[dict], stats: dict) -> list[str]:
    """Only the problems, and only when there are any — a clean catalog should
    produce a short report, not a wall of green checkmarks."""
    lines = ["## Audit", ""]
    clean = True

    if stats["no_executor"]:
        clean = False
        names = ", ".join(f"`{n}`" for n in stats["no_executor"])
        lines += [
            f"- ⚠️ **No executor**: {names}. The planner can plan these, but "
            "`TaskRunnerWorkflow` has nothing to run — they cost catalog tokens on "
            "every request and fail if selected.",
            "",
        ]

    incomplete = [t for t in tools if t["missing_sections"]]
    if incomplete:
        clean = False
        lines += [
            "- ⚠️ **Incomplete descriptions.** These docstrings are the planner's "
            "only instructions for when to pick a node; a missing `Do not use:` or "
            "`Example queries:` is a known source of misroutes "
            "(docs/eval-strategy.md).",
            "",
            "| node type | missing |",
            "|---|---|",
        ]
        for tool in incomplete:
            missing = ", ".join(f"`{s}`" for s in tool["missing_sections"])
            lines.append(f"| `{tool['node_type']}` | {missing} |")
        lines.append("")

    if clean:
        lines += ["Nothing to flag.", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="gpt-4.1",
        help="Model whose tokenizer to count with (default: gpt-4.1, the model "
        "pinned for goal generation — the call that reads the whole catalog).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the report to this file "
        "(e.g. evals/results/<campaign>/tools_catalog.md).",
    )
    args = parser.parse_args()

    report = build_report(current_git_sha(), datetime.now(timezone.utc), args.model)
    print(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
