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

# restore the postgres books data from a file
.PHONY: postgres-restore-books
postgres-restore-books:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)data/backup/backup.sql
	@echo "PostgreSQL data restored from $(MAKEFILE_DIR)data/backup/backup.sql

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

# dump test_runs data to a timestamped .sql file (data only, restorable via psql <)
# — the suite/case links written by evals/run_suites.py, keyed by chat_id
.PHONY: postgres-dump-test-runs
postgres-dump-test-runs:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB --table=test_runs --data-only --column-inserts \
		> $(MAKEFILE_DIR)data/test_runs_$$(date +%Y%m%d_%H%M%S).sql
	@echo "test_runs dumped to $(MAKEFILE_DIR)data/"

# dump chat_runs plus every table FK'd to it (feedback, test_runs) into ONE
# timestamped .sql file, so the set is restored/moved together. pg_dump
# topo-sorts data-only dumps by FK dependency, so chat_runs's INSERTs land
# before feedback's/test_runs's in the file — required since these are plain
# (non-deferred) constraints: a referencing row inserted before its chat_runs
# row would fail. Restore with: make postgres-query FILE=data/<this file>
.PHONY: postgres-dump-chat-runs-cascade
postgres-dump-chat-runs-cascade:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB \
			--table=chat_runs --table=feedback --table=test_runs \
			--data-only --column-inserts \
		> $(MAKEFILE_DIR)data/chat_runs_cascade_$$(date +%Y%m%d_%H%M%S).sql
	@echo "chat_runs + feedback + test_runs dumped to $(MAKEFILE_DIR)data/"

# wipe all recorded chat runs (dev convenience — irreversible)
# CASCADE: feedback.chat_id and test_runs.chat_id both reference chat_runs,
# and TRUNCATE refuses a table with incoming FK references (even empty ones)
# unless told to cascade — this also empties feedback and test_runs.
# NOTE: for dev
.PHONY: postgres-clear-chat-runs
postgres-clear-chat-runs:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "TRUNCATE TABLE chat_runs CASCADE;"
	@echo "chat_runs table cleared (feedback, test_runs cascaded)"

# wipe all recorded feedback (dev convenience — irreversible)
# NOTE: for dev
.PHONY: postgres-clear-feedback
postgres-clear-feedback:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "TRUNCATE TABLE feedback;"
	@echo "feedback table cleared"

# wipe all recorded suite/case links (dev convenience — irreversible).
# Standalone use only — postgres-clear-chat-runs already cascades into this
# table, so postgres-logs-clear doesn't need to call it too.
# NOTE: for dev
.PHONY: postgres-clear-test-runs
postgres-clear-test-runs:
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "TRUNCATE TABLE test_runs;"
	@echo "test_runs table cleared"

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

# in-process API tests: real FastAPI app over httpx ASGI transport, stores
# faked via dependency_overrides — no DB or LLM needed, safe to run anywhere
.PHONY: tests-integration
tests-integration:
	poetry run pytest -s tests/integration/

.PHONY: tests-all
tests-all:
	poetry run pytest -s tests/unit/ tests/integration/

.PHONY: typecheck
typecheck:
	poetry run pyright

.PHONY: playground
playground:
	poetry run python playground/scratch.py

.PHONY: local-end-to-end-test
local-end-to-end-test:
	./tests/scripts/local_end_to_end_test.sh

# Query-suite / eval-run commands (query-suite, query-suite-all, ...) live in
# evals/makefile, next to the suite JSONs and runner they drive. Pulled in here
# so they still run as `make query-suite-all` from backend/ (cwd stays backend/,
# so the relative suite/log paths in those recipes resolve).
include $(MAKEFILE_DIR)evals/makefile

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