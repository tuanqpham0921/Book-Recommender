# -------------------------------------------------------------------
# Eval-run commands — moved here from backend/Makefile.
#
# Pulled into the root Makefile via `include makefile`, so `make query-suite-all`
# etc. work from backend/. Every path below is anchored to $(EVALS_DIR) rather
# than to cwd, so the same targets also work invoked from evals/ directly
# (`make -f makefile query-suite`). They used to be bare relative paths, which
# silently only worked from evals/ despite the root Makefile documenting the
# opposite.
#
# The postgres dump targets this flow needs (README step 2) already live in the
# root Makefile: `make postgres-dump-chat-runs` / `make postgres-dump-feedback`
# (they used to be duplicated here — dropped to avoid override warnings on include).
# -------------------------------------------------------------------

# Absolute path to this file's directory, resolved at parse time. Must stay
# above the variables that build on it.
EVALS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# Query-suite runners POST to a RUNNING backend — start it first with `make dev`.
# Override the target or forward extra runner flags, e.g.
#   make query-suite-all ARGS="--difficulty easy"
#   make query-suite BASE_URL=http://localhost:9000
#
# LIMIT / SLEEP are the debug knobs, applied to every suite target:
#   make query-suite LIMIT=3 SLEEP=0     # 3 queries, no rate-limit wait
#   make query-suite-smoke               # the same thing, named
# Both default to the runner's own defaults (all queries, 45s between them to
# stay under the OpenAI TPM limit) — a full campaign needs that sleep, a debug
# loop does not. ARGS is appended after them, so a flag there still wins.
#
# Each run is tee'd to a timestamped per-suite log under $(LOG_DIR); console
# output still shows live (python -u keeps it unbuffered through the pipe).
BASE_URL ?= http://localhost:8000
ARGS ?=
LIMIT ?=
SLEEP ?=
SMOKE_LIMIT ?= 3
SUITES_DIR := $(EVALS_DIR)suites
LOG_DIR ?= $(EVALS_DIR)logs/query_suites
RUN_SUITE = poetry run python -u $(EVALS_DIR)run_suites.py --base-url $(BASE_URL) \
	$(if $(LIMIT),--limit $(LIMIT)) $(if $(SLEEP),--sleep $(SLEEP)) $(ARGS) --suite

# run the base query suite against a running backend (make dev first)
.PHONY: query-suite
query-suite:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) $(SUITES_DIR)/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log

# DEBUG LOOP — first $(SMOKE_LIMIT) queries of the base suite, no sleep between
# them. Records to chat_runs/test_runs like any other run, so `make suite-goals`
# and `make suite-stats` work on it; override with SMOKE_LIMIT=n.
.PHONY: query-suite-smoke
query-suite-smoke:
	@$(MAKE) query-suite LIMIT=$(SMOKE_LIMIT) SLEEP=0

# run the adversarial suite (edge cases, injections, overflow — ids 301+)
.PHONY: query-suite-adversarial
query-suite-adversarial:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log

# run the stress suite (buffer overflow + confusing cross-domain plans — ids 401+)
.PHONY: query-suite-stress
query-suite-stress:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log

# run the extended-catalog scaling suite (ids 101+)
# its tool schemas are still parked in playground/app_mock, not wired into the registry
.PHONY: query-suite-extended
query-suite-extended:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

# fire ALL suites CONCURRENTLY at the backend (each mints its own test_ session,
# so this simulates several users hitting the server at once). Console output is
# interleaved and tagged per-suite; each suite's own clean log is written to
# $(LOG_DIR)/<suite>_<ts>.log. The shell blocks until every suite finishes.
.PHONY: query-suite-all
query-suite-all:
	@mkdir -p $(LOG_DIR)
	@echo "Firing all 4 suites concurrently at $(BASE_URL) — make sure the backend is running (make dev)."
	@ts=$$(date +%Y%m%d_%H%M%S); \
	echo "per-suite logs -> $(LOG_DIR)/*_$$ts.log"; \
	$(RUN_SUITE) $(SUITES_DIR)/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$ts.log | sed 's/^/[base]   /' & \
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$ts.log | sed 's/^/[adv]    /' & \
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$ts.log | sed 's/^/[stress] /' & \
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$ts.log | sed 's/^/[ext]    /' & \
	wait; \
	echo "All suites finished. Logs: $(LOG_DIR)/*_$$ts.log"

# run ALL suites SEQUENTIALLY (clean, un-interleaved output; stops on first error)
.PHONY: query-suite-all-seq
query-suite-all-seq:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) $(SUITES_DIR)/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) $(SUITES_DIR)/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

# run each suite in its own tmux pane (literal "separate terminals" view).
# Requires tmux. Each pane also tee's to its own log under $(LOG_DIR). Panes stay
# open after each suite finishes; press Enter in a pane to close it.
.PHONY: query-suite-all-tmux
query-suite-all-tmux:
	@command -v tmux >/dev/null 2>&1 || { echo "tmux not installed — use 'make query-suite-all' instead."; exit 1; }
	@mkdir -p $(LOG_DIR)
	@tmux kill-session -t query_suites 2>/dev/null || true
	tmux new-session  -d -s query_suites -c "$(CURDIR)" '$(RUN_SUITE) $(SUITES_DIR)/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[base] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) $(SUITES_DIR)/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[adv] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) $(SUITES_DIR)/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[stress] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) $(SUITES_DIR)/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[ext] done — press Enter to close"; read _'
	tmux select-layout -t query_suites tiled
	tmux attach-session -t query_suites

# CAMPAIGN=<name> files both reports under results/<name>/ with fixed names,
# per the campaign convention in the README (that directory also holds the SQL
# dumps and the hand-written review). Each report keeps its own filename, so
# suite-reports can't have one clobber the other:
#
#   make suite-reports CAMPAIGN=v1_baseline
#     -> results/v1_baseline/system_goals.md + results/v1_baseline/report.md
#
# Without it, suite-goals falls back to results/system_goals_<timestamp>.md and
# suite-stats just prints. ARGS is appended last, so an explicit --output in
# there still wins. The scripts create the directory themselves.
CAMPAIGN ?=
CAMPAIGN_DIR = $(EVALS_DIR)results/$(CAMPAIGN)
campaign_out = $(if $(CAMPAIGN),--output $(CAMPAIGN_DIR)/$(1))

# CORRECTNESS — the golden test. Joins test_runs (written by the runner) with
# chat_runs and diffs each run's accepted goal types against expected_nodes in
# the suite JSONs (matched/missing/extra). Says nothing about spend. Latest run
# per case by default; forward flags via ARGS, e.g. ARGS="--all".
.PHONY: suite-goals
suite-goals:
	poetry run python $(EVALS_DIR)report_system_goals.py $(call campaign_out,system_goals.md) $(ARGS)

# COST — tokens, dollars, latency and failures per run, plus a per-model spend
# split. No expectation checking. Always prints to stdout; also saves when
# CAMPAIGN (or an explicit --output) is given.
.PHONY: suite-stats
suite-stats:
	poetry run python $(EVALS_DIR)report.py $(call campaign_out,report.md) $(ARGS)

# both post-processors in one go — the usual move after a campaign
.PHONY: suite-reports
suite-reports: suite-goals suite-stats

# TODO: make the path to variable names
# make a better run make, so it dumps and copy the logs over