# Variables
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ENV_FILE := $(MAKEFILE_DIR)/config/.env
DOCKER_COMPOSE_FILE := $(MAKEFILE_DIR)/docker-compose.yml
POSTGRES_SERVICE := postgres
# Must match container_name for the postgres service in docker-compose.yml
POSTGRES_CONTAINER := book-rec-postgres

# -------------------
# General commands
# -------------------

# Poetry commands
.PHONY: install
install:
	poetry install

# Local development (native FastAPI)
.PHONY: dev
dev:
	LOG_LEVEL=INFO poetry run uvicorn app.main:app --reload --reload-include "*.py" --reload-include "*.env"

# run the ingestion script
.PHONY: ingestion
ingestion:
	LOG_LEVEL=INFO poetry run python -m db.ingestion.main

# expose the local API (make dev) to the internet via ngrok.
# copy the printed https://*.ngrok-free.dev URL into
# `make -C ../frontend deploy-tunnel URL=<that url>`
.PHONY: tunnel
tunnel:
	ngrok http 8000

# clear the pycache
.PHONY: clean
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
	find . -name "*.pyo" -delete
	find . -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null

# -------------------
# PostgreSQL commands
# -------------------

# Local development (databases + native FastAPI)
.PHONY: postgres-start
postgres-start:
	docker compose --env-file $(ENV_FILE) -f $(DOCKER_COMPOSE_FILE) up $(POSTGRES_SERVICE) -d
	@echo "Databases started. Run 'make dev' to start API"

# stop the postgres container
.PHONY: postgres-stop
postgres-stop:
	docker compose -f $(DOCKER_COMPOSE_FILE) down $(POSTGRES_SERVICE)
	@echo "PostgreSQL container stopped (does not remove volumes)"

# enter postgres CLI (loads POSTGRES_USER / POSTGRES_DB from config/.env)
.PHONY: postgres-cli
postgres-cli:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -it -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB

# run an ad hoc query file against the dev postgres container (default: data/sql_dev_commands.sql)
# usage: make postgres-query [FILE=data/some_other_file.sql]
.PHONY: postgres-query
postgres-query:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)$(or $(FILE),data/sql_dev_commands.sql)

# restore plain-SQL backup (data/backup.sql) into the compose postgres container
.PHONY: postgres-restore
postgres-restore:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)data/backup.sql

# dump the postgres data to a file (overwrites existing backup.sql)
# currently throw an error because entry point init and backup does have IF NOT EXISTS
.PHONY: postgres-dump
postgres-dump:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB > $(MAKEFILE_DIR)data/backup.sql
	@echo "PostgreSQL data dumped to $(MAKEFILE_DIR)data/backup.sql"

# restore the postgres data from a file
.PHONY: postgres-restore-data
postgres-restore-data:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)data/backup.sql
	@echo "PostgreSQL data restored from $(MAKEFILE_DIR)data/backup.sql"

# dump chat_runs data to a timestamped .sql file (data only, restorable via psql <)
.PHONY: postgres-dump-chat-runs
postgres-dump-chat-runs:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB --table=chat_runs --data-only --column-inserts \
		> $(MAKEFILE_DIR)data/chat_runs_$$(date +%Y%m%d_%H%M%S).sql
	@echo "chat_runs dumped to $(MAKEFILE_DIR)data/"

# dump feedback data to a timestamped .sql file (data only, restorable via psql <)
.PHONY: postgres-dump-feedback
postgres-dump-feedback:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB --table=feedback --data-only --column-inserts \
		> $(MAKEFILE_DIR)data/feedback_$$(date +%Y%m%d_%H%M%S).sql
	@echo "feedback dumped to $(MAKEFILE_DIR)data/"

# wipe all recorded chat runs (dev convenience — irreversible)
# NOTE: for dev
.PHONY: postgres-clear-chat-runs
postgres-clear-chat-runs:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "TRUNCATE TABLE chat_runs;"
	@echo "chat_runs table cleared"

# wipe all recorded feedback (dev convenience — irreversible)
# NOTE: for dev
.PHONY: postgres-clear-feedback
postgres-clear-feedback:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "TRUNCATE TABLE feedback;"
	@echo "feedback table cleared"

# wipe all recorded chat runs and feedback (dev convenience — irreversible)
.PHONY: postgres-logs-clear
postgres-logs-clear:
	make postgres-clear-feedback
	make postgres-clear-chat-runs

# -------------------
# Docker commands
# -------------------

# clean the docker containers and volumes
.PHONY: docker-clean-all
docker-clean-all:
	docker compose --env-file $(ENV_FILE) -f $(DOCKER_COMPOSE_FILE) down -v
	@echo "Docker containers and volumes cleaned"

# -------------------
# Testing commands
# -------------------

.PHONY: tests
tests:
	poetry run pytest -s tests/unit/

.PHONY: typecheck
typecheck:
	poetry run pyright

.PHONY: playground
playground:
	poetry run python playground/scratch.py

.PHONY: local-end-to-end-test
local-end-to-end-test:
	./tests/scripts/local_end_to_end_test.sh

# Query-suite runners POST to a RUNNING backend — start it first with `make dev`.
# Override the target or forward extra runner flags, e.g.
#   make query-suite-all ARGS="--difficulty easy"
#   make query-suite BASE_URL=http://localhost:9000
# Each run is tee'd to a timestamped per-suite log under $(LOG_DIR); console
# output still shows live (python -u keeps it unbuffered through the pipe).
BASE_URL ?= http://localhost:8000
ARGS ?=
LOG_DIR ?= logs/query_suites
RUN_SUITE = poetry run python -u tests/scripts/run_query_suites.py --base-url $(BASE_URL) $(ARGS) --suite

# run the base query suite against a running backend (make dev first)
.PHONY: query-suite
query-suite:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) tests/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log

# run the adversarial suite (edge cases, injections, overflow — ids 301+)
.PHONY: query-suite-adversarial
query-suite-adversarial:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) tests/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log

# run the stress suite (buffer overflow + confusing cross-domain plans — ids 401+)
.PHONY: query-suite-stress
query-suite-stress:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) tests/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log

# run the extended-catalog scaling suite (new tool schemas, ids 101+)
# parked: schemas live in playground/app_mock, not wired into the registry
.PHONY: query-suite-extended
query-suite-extended:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) playground/app_mock/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

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
	$(RUN_SUITE) tests/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$ts.log | sed 's/^/[base]   /' & \
	$(RUN_SUITE) tests/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$ts.log | sed 's/^/[adv]    /' & \
	$(RUN_SUITE) tests/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$ts.log | sed 's/^/[stress] /' & \
	$(RUN_SUITE) playground/app_mock/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$ts.log | sed 's/^/[ext]    /' & \
	wait; \
	echo "All suites finished. Logs: $(LOG_DIR)/*_$$ts.log"

# run ALL suites SEQUENTIALLY (clean, un-interleaved output; stops on first error)
.PHONY: query-suite-all-seq
query-suite-all-seq:
	@mkdir -p $(LOG_DIR)
	$(RUN_SUITE) tests/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) tests/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) tests/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log
	$(RUN_SUITE) playground/app_mock/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log

# run each suite in its own tmux pane (literal "separate terminals" view).
# Requires tmux. Each pane also tee's to its own log under $(LOG_DIR). Panes stay
# open after each suite finishes; press Enter in a pane to close it.
.PHONY: query-suite-all-tmux
query-suite-all-tmux:
	@command -v tmux >/dev/null 2>&1 || { echo "tmux not installed — use 'make query-suite-all' instead."; exit 1; }
	@mkdir -p $(LOG_DIR)
	@tmux kill-session -t query_suites 2>/dev/null || true
	tmux new-session  -d -s query_suites -c "$(MAKEFILE_DIR)" '$(RUN_SUITE) tests/query_suite.json 2>&1 | tee $(LOG_DIR)/base_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[base] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(MAKEFILE_DIR)" '$(RUN_SUITE) tests/query_suite_adversarial.json 2>&1 | tee $(LOG_DIR)/adversarial_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[adv] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(MAKEFILE_DIR)" '$(RUN_SUITE) tests/query_suite_stress.json 2>&1 | tee $(LOG_DIR)/stress_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[stress] done — press Enter to close"; read _'
	tmux split-window  -t query_suites  -c "$(MAKEFILE_DIR)" '$(RUN_SUITE) playground/app_mock/query_suite_extended.json 2>&1 | tee $(LOG_DIR)/extended_$$(date +%Y%m%d_%H%M%S).log; echo; echo "[ext] done — press Enter to close"; read _'
	tmux select-layout -t query_suites tiled
	tmux attach-session -t query_suites

# .Phony: lint
# lint:
# 	poetry run ruff check --fix clients/ tests/unit/clients/
#   poetry run black common/utils/ tests/unit/common/utils/

# -------------------
# Evals commands
# -------------------

# run the chat_runs eval summary (total/avg tokens & duration, ok vs not-ok, runtime_error counts)
.PHONY: chat-runs-eval
chat-runs-eval:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)db/chat_run_eval.sql