# backend/evals

The planner eval harness — versioned query suites with per-case node expectations,
a runner, and report generators. **Why it's built this way and where it's headed:**
[docs/eval-strategy.md](../../docs/eval-strategy.md).

## Suites (`suites/`)

| Suite | Cases | Targets |
|---|---|---|
| `query_suite.json` | 70 | Core node set, easy→hard |
| `query_suite_adversarial.json` | 54 | Rejection behavior (17 cases intentionally expect no nodes) |
| `query_suite_extended.json` | 48 | Catalog scaling — needs the registry PLAYGROUND EXTENSION block enabled |
| `query_suite_stress.json` | 9 | Buffer/overflow, confusing chains |

Each case: `id`, `query`, `difficulty`, `expected_nodes`, `note` (+ `category`/`domain`
in adversarial/stress).

## Workflow

Backend must be running (`make dev`). Every path in `makefile` is anchored to the
evals directory, so these run identically from `backend/` (via the root Makefile's
include) or from `evals/` itself (`make -f makefile <target>`). Run logs land in
`evals/logs/query_suites/` either way — override with `LOG_DIR=...`.

```bash
make query-suite            # base suite
make query-suite-adversarial / -extended / -stress
make query-suite-all        # all 4 concurrently (doubles as the concurrency test)
make query-suite-all-seq    # sequential; -all-tmux for one pane per suite
make query-suite-smoke      # first 3 queries, no sleep — the debug loop
```

`LIMIT=n` caps the queries per suite and `SLEEP=n` overrides the 45s the runner waits
between them; both apply to every target above. A full campaign needs that sleep to
stay under the OpenAI TPM limit, a debug run does not — so `make query-suite LIMIT=3
SLEEP=0` finishes in seconds. `query-suite-smoke` is exactly that pairing (override the
count with `SMOKE_LIMIT=n`). Smoke runs record to `chat_runs`/`test_runs` like any
other, so both reports work on them.

The runner (`run_suites.py`) POSTs each query to `/session/{id}/message`, consumes the
SSE stream, and records its `test_runs` row (chat_id FK → `chat_runs` + suite name +
case id) right away — not batched until the run finishes — so an interrupted run still
has everything it completed recorded. Sessions are minted as `test_<uuid8>` so eval
traffic is filterable. By default it sleeps 45s between queries to stay under the
OpenAI TPM rate limit (`--sleep 0` to disable). Flags: `--suite`, `--difficulty`,
`--ids`, `--new-session-per-query`, `--no-record`, `--sleep`.

Then post-process:

```bash
make suite-goals   # report_system_goals.py — CORRECTNESS. Joins test_runs ⋈ chat_runs
                   # and diffs accepted goal types vs expected_nodes
                   # (matched/missing/extra) → results/system_goals_<timestamp>.md
make suite-stats   # report.py — COST. ok/failed, runtime_error, duration, tokens
                   # incl. cached + cache hit rate, dollars, and a per-model split
make suite-reports # both
```

Both take `ARGS="--all"` for every run (default: latest run per case), `ARGS="--suite
<stem>"` (repeatable) and `ARGS="--output <path>"`. The split is deliberate: the goals
report is the pass/fail gate and mentions no numbers that change run to run, so its
diffs stay readable; the cost report is where tokens, dollars and latency live.

## Tool catalog (`tools_catalog.py`)

```bash
make tools-catalog                        # print
make tools-catalog CAMPAIGN=v1_baseline   # -> results/v1_baseline/tools_catalog.md
make tools-catalog ARGS="--model gpt-5-nano"
```

The odd one out: it reads the **live registry**, not the database, so it needs no
backend, no prior run and no `chat_runs` rows — it describes the code at the current
commit. Run it after adding or editing a node.

Every registered node is a tool the planner is told about, and its class docstring *is*
the tool description — so the catalog is prompt text billed on **every** request,
whether or not any of those tools get used. The report gives the tool count per tier,
each tool's `Purpose:` line, per-tool token cost with its share of the block, and what
the whole thing costs per request, uncached and cached (the catalog is byte-identical every time, so the cached
column is the steady state — `make suite-stats`'s measured hit rate says how close you
are to it). Two token figures, paid at different points:

- **catalog tokens** — the whole `format_node_type_catalog()` block, rendered into both
  the goal-generator and parse-response prompts, so it is paid twice per request;
- **schema tokens** — one node's JSON function-tool schema, sent by
  `strategy_classification.py` only for the nodes an accepted goal targets.

It also audits: nodes registered with no executor (planned but unrunnable, still paying
catalog tokens) and docstrings missing a canonical section — a missing `Do not use:` or
`Example queries:` is a known misroute source, see
[docs/eval-strategy.md](../../docs/eval-strategy.md).

Dollar figures come from `cost_usd`, stamped onto each run's `token_usage` when it was
recorded (rates in [config/pricing.py](../config/pricing.py)) — **frozen at record time**,
so re-running a report never backfills or reprices history. Two distinct gaps get called
out rather than hidden:

- a run with no `cost_usd` at all (predates cost tracking) counts as **unpriced** in the
  summary row, never as free;
- a run whose `token_usage.unpriced_models` is non-empty still *has* a cost, just too low
  — the report prints an explicit "costs are understated" warning naming the models. Add
  them to `config/pricing.py`; only future runs will be right.

## Repo sizing (`app_docs/`)

Also not about planner quality: `app_docs/token_budget.ipynb` counts the repo's own code
and docs to size an embedding index for **project/code guidance** — tokens, chunks, index
MB and dollars, plus retrieval-vs-whole-corpus cost per question. Local counting only, no
API calls and no database. See [app_docs/README.md](app_docs/README.md).

## Campaign convention (`results/`)

Per campaign: a directory with the raw SQL dumps of `chat_runs` + `feedback` (dump
before deleting — `test_runs` cascades away with `chat_runs`), the generated reports,
and a hand-written review (`personal_report.md`, optionally an AI review). See
`results/dev_f5a12966_7_13_initial/` for the shape.

`CAMPAIGN=<name>` files both reports into `results/<name>/` under fixed names, so
`suite-reports` can't have one clobber the other:

```bash
make suite-reports CAMPAIGN=v1_baseline
# -> results/v1_baseline/system_goals.md + results/v1_baseline/report.md
```
