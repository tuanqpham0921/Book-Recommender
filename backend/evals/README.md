# backend/evals

The planner eval harness — versioned query suites with per-case node expectations,
a runner, and report generators. **Why it's built this way and where it's headed:**
[docs/eval-strategy.md](../../docs/eval-strategy.md).

## Suites (`suites/`)

| Suite | Cases | Targets |
|---|---|---|
| `query_suite.json` | 50 | Core node set, easy→hard |
| `query_suite_adversarial.json` | 52 | Rejection behavior (12 cases intentionally expect no nodes) |
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
```

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
make suite-report  # report.py — COST. ok/failed, runtime_error, duration, tokens
                   # incl. cached + cache hit rate, dollars, and a per-model split
make suite-reports # both
```

Both take `ARGS="--all"` for every run (default: latest run per case), `ARGS="--suite
<stem>"` (repeatable) and `ARGS="--output <path>"`. The split is deliberate: the goals
report is the pass/fail gate and mentions no numbers that change run to run, so its
diffs stay readable; the cost report is where tokens, dollars and latency live.

Dollar figures come from `cost_usd`, stamped onto each run's `token_usage` when it was
recorded (rates in [config/pricing.py](../config/pricing.py)). Runs recorded before cost
tracking landed have no `cost_usd` and are counted as **unpriced**, not free — the
summary row says how many, so a total is never quietly understated.

## Campaign convention (`results/`)

Per campaign: a directory with the raw SQL dumps of `chat_runs` + `feedback` (dump
before deleting — `test_runs` cascades away with `chat_runs`), the generated
`eval_*.md` / stats reports, and a hand-written review (`personal_report.md`,
optionally an AI review). See `results/dev_f5a12966_7_13_initial/` for the shape.
