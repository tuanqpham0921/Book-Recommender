# -------------------------------------------------------------------
# Eval-run commands — moved here from backend/Makefile.
#
# Pulled into the root Makefile via `include evals/makefile`, so from
# backend/ these run exactly as before: `make query-suite-all`, etc. The root
# Makefile is invoked from backend/, so cwd is backend/ and the relative paths
# below (evals/, logs/) resolve there. $(CURDIR) is that backend/
# dir — used for the tmux panes' working directory.
#
# The postgres dump targets this flow needs (README step 2) already live in the
# root Makefile: `make postgres-dump-chat-runs` / `make postgres-dump-feedback`
# (they used to be duplicated here — dropped to avoid override warnings on include).
# -------------------------------------------------------------------

# Query-suite runners POST to a RUNNING backend — start it first with `make dev`.
# Override the target or forward extra runner flags, e.g.
#   make query-suite-all ARGS="--difficulty easy"
#   make query-suite BASE_URL=http://localhost:9000
# Each run is tee'd to a timestamped per-suite log under $(LOG_DIR); console
# output still shows live (python -u keeps it unbuffered through the pipe).
BASE_URL ?= http://localhost:8000
ARGS ?=
LOG_DIR ?= logs/query_suites
RUN_SUITE = poetry run python -u evals/run_suites.py --base-url $(BASE_URL) $(ARGS) --suite

# run the base query suite against a running backend (make dev first)
.PHONY: query-suite
query-suite:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) evals/suites/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log

# run the adversarial suite (edge cases, injections, overflow — ids 301+)
.PHONY: query-suite-adversarial
query-suite-adversarial:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) evals/suites/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log

# run the stress suite (buffer overflow + confusing cross-domain plans — ids 401+)
.PHONY: query-suite-stress
query-suite-stress:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) evals/suites/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log

# run the extended-catalog scaling suite (ids 101+)
# its tool schemas are still parked in playground/app_mock, not wired into the registry
.PHONY: query-suite-extended
query-suite-extended:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) evals/suites/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

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
	$(RUN_SUITE) evals/suites/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$ts.log | sed 's/^/[base]   /' & \
	$(RUN_SUITE) evals/suites/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$ts.log | sed 's/^/[adv]    /' & \
	$(RUN_SUITE) evals/suites/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$ts.log | sed 's/^/[stress] /' & \
	$(RUN_SUITE) evals/suites/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$ts.log | sed 's/^/[ext]    /' & \
	wait; \
	echo "All suites finished. Logs: $(LOG_DIR)/*_$$ts.log"

# run ALL suites SEQUENTIALLY (clean, un-interleaved output; stops on first error)
.PHONY: query-suite-all-seq
query-suite-all-seq:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) evals/suites/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) evals/suites/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) evals/suites/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) evals/suites/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

# run each suite in its own tmux pane (literal "separate terminals" view).
# Requires tmux. Each pane also tee's to its own log under $(LOG_DIR). Panes stay
# open after each suite finishes; press Enter in a pane to close it.
.PHONY: query-suite-all-tmux
query-suite-all-tmux:
	@command -v tmux >/dev/null 2>&1 || { echo "tmux not installed — use 'make query-suite-all' instead."; exit 1; }
	@mkdir -p $(LOG_DIR)
	@tmux kill-session -t query_suites 2>/dev/null || true
	tmux new-session  -d -s query_suites -c "$(CURDIR)" '$(RUN_SUITE) evals/suites/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[base] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) evals/suites/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[adv] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) evals/suites/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[stress] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(CURDIR)" '$(RUN_SUITE) evals/suites/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[ext] done — press Enter to close"; read _'
	tmux select-layout -t query_suites tiled
	tmux attach-session -t query_suites

# post-process suite runs: joins test_runs (written by the runner) with
# chat_runs and diffs each run's accepted goal types against expected_nodes
# in the suite JSONs (matched/missing/extra). Saves a markdown report to
# evals/results/eval_<timestamp>.md. Latest run per case by default; forward
# flags via ARGS, e.g. make suite-eval ARGS="--all --output evals/results/my_campaign/eval.md"
.PHONY: suite-eval
suite-eval:
	poetry run python evals/eval.py $(ARGS)

# TODO: touch or echo a new personal_review
