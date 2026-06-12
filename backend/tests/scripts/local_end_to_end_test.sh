#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${BACKEND_DIR}"

APP_PID=""

cleanup() {
  if [[ -n "${APP_PID}" ]] && kill -0 "${APP_PID}" 2>/dev/null; then
    kill "${APP_PID}" 2>/dev/null || true
    wait "${APP_PID}" 2>/dev/null || true
  fi

  make docker-clean-all >/dev/null 2>&1 || true
}

trap cleanup EXIT

LOG_LEVEL=INFO poetry run pytest -s tests/unit

make docker-clean-all
make postgres-start
sleep 5

LOG_LEVEL=INFO poetry run python -m db.ingestion.main

LOG_LEVEL=INFO poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
APP_PID=$!

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:8000/health >/dev/null

SESSION_ID="$(curl -fsS -X POST http://127.0.0.1:8000/session/new | poetry run python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

curl -fsS \
  -X POST "http://127.0.0.1:8000/session/${SESSION_ID}/message" \
  -H "Content-Type: application/json" \
  -d '{"message":"book similar to Pride and Prejudice"}' \
  >/dev/null