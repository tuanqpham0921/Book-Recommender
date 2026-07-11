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
.PHONY: postgres-dev-reset-log
postgres-dev-reset-log:
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

# run the tests
.PHONY: tests
tests:
	poetry run pytest -s tests/unit/common/utils --cov=common/utils --cov-report=term-missing
	poetry run pytest -s tests/unit/clients --cov=clients/ --cov-report=term-missing
	poetry run pytest -s tests/unit/app/common/test_messages.py --cov=app.common.messages --cov-report=term-missing
	poetry run pytest -s tests/unit/app/common/test_mermaid.py --cov=app.common.mermaid --cov-report=term-missing
	poetry run pytest -s tests/unit/app/common/test_prompt_loader.py --cov=app.common.prompt_loader --cov-report=term-missing
	poetry run pytest -s tests/unit/db/test_async_engine.py --cov=db.async_engine --cov-report=term-missing
	poetry run pytest -s tests/unit/config/test_settings.py --cov=config.settings --cov-report=term-missing 
	poetry run pytest -s tests/unit/app/domains/planner --cov=app/domains/planner --cov-report=term-missing
	poetry run pytest -s tests/unit/app/orchestration --cov=app/orchestration --cov-report=term-missing

# poetry run pytest -s tests/unit/app/domains/planner/test_strategy_classification.py

.PHONY: tests-all
tests-all:
	poetry run pytest -s tests/unit/

.PHONY: typecheck
typecheck:
	poetry run pyright

.PHONY: playground
playground:
	poetry run python playground.py

.PHONY: local-end-to-end-test
local-end-to-end-test:
	./tests/scripts/local_end_to_end_test.sh

# run the base query suite against a running backend (make dev first)
.PHONY: query-suite
query-suite:
	poetry run python tests/scripts/run_query_suites.py

# run the extended-catalog scaling suite (new tool schemas, ids 101+)
.PHONY: query-suite-extended
query-suite-extended:
	poetry run python tests/scripts/run_query_suites.py --suite tests/query_suite_extended.json

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
		psql -U $$POSTGRES_USER -d $$POSTGRES_DB < $(MAKEFILE_DIR)data/sql_eval_commands.sql