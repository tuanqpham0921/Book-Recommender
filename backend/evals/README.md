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

Backend must be running (`make dev`). All targets from `backend/`:

```bash
make query-suite            # base suite
make query-suite-adversarial / -extended / -stress
make query-suite-all        # all 4 concurrently (doubles as the concurrency test)
make query-suite-all-seq    # sequential; -all-tmux for one pane per suite
```

The runner (`run_suites.py`) POSTs each query to `/session/{id}/message`, consumes the
SSE stream, and records one `test_runs` row per query (chat_id FK → `chat_runs` +
suite name + case id). Sessions are minted as `test_<uuid8>` so eval traffic is
filterable. Flags: `--suite`, `--difficulty`, `--ids`, `--new-session-per-query`,
`--no-record`.

Then post-process:

```bash
make suite-eval    # eval.py: joins test_runs ⋈ chat_runs, diffs accepted goal types
                   # vs expected_nodes (matched/missing/extra) →
                   # results/eval_<timestamp>.md. ARGS="--all" for every run
                   # (default: latest per case); ARGS="--output <path>" to name it
make suite-report  # report.py: plain outcomes (ok/failed, runtime_error, duration,
                   # tokens) — no expectation checking
```

## Campaign convention (`results/`)

Per campaign: a directory with the raw SQL dumps of `chat_runs` + `feedback` (dump
before deleting — `test_runs` cascades away with `chat_runs`), the generated
`eval_*.md` / stats reports, and a hand-written review (`personal_report.md`,
optionally an AI review). See `results/dev_f5a12966_7_13_initial/` for the shape.
