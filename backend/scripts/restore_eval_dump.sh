#!/usr/bin/env bash
# Restore an eval dump pair (data-only, --column-inserts) taken under the
# pre-review-queue schema into the current schema:
#   chat_runs_*.sql — legacy liked/reviewed columns absorbed and discarded
#   feedback_*.sql  — legacy report/reaction rows folded into review rows
#                     (one per chat_id + reviewing session_id), raw rows
#                     archived in feedback_legacy
# Rows already present (by primary key / review key) are skipped, so
# re-running is safe. Either dump may be absent; the newest of each pattern
# in the directory is used.
#
# Expects POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_CONTAINER
# in the environment — invoke via `make postgres-restore-eval DIR=...`.
set -euo pipefail

DUMP_DIR="${1:?usage: restore_eval_dump.sh <dir-with-dumps>}"

run_psql() {
    docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$POSTGRES_CONTAINER" \
        psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=1 "$@"
}

newest() {
    ls "$DUMP_DIR"/$1 2>/dev/null | sort | tail -1 || true
}

CHAT_DUMP=$(newest 'chat_runs_*.sql')
FB_DUMP=$(newest 'feedback_*.sql')
[ -z "$CHAT_DUMP" ] && [ -z "$FB_DUMP" ] && {
    echo "no chat_runs_*.sql or feedback_*.sql found in $DUMP_DIR" >&2
    exit 1
}

if [ -n "$CHAT_DUMP" ]; then
    echo "restoring chat runs from $CHAT_DUMP"
    run_psql <<'SQL'
DROP TABLE IF EXISTS chat_runs_staging;
CREATE TABLE chat_runs_staging (LIKE chat_runs);
ALTER TABLE chat_runs_staging
    ADD COLUMN IF NOT EXISTS liked BOOLEAN,
    ADD COLUMN IF NOT EXISTS reviewed BOOLEAN;
SQL
    sed 's/^INSERT INTO public\.chat_runs /INSERT INTO public.chat_runs_staging /' "$CHAT_DUMP" | run_psql
    run_psql <<'SQL'
INSERT INTO chat_runs (chat_id, session_id, created_at, user_message, ok,
                       runtime_error, duration_s, total_tokens, mermaid,
                       planner, tasks, sse_events)
SELECT chat_id, session_id, created_at, user_message, ok,
       runtime_error, duration_s, total_tokens, mermaid,
       planner, tasks, sse_events
FROM chat_runs_staging
ON CONFLICT (chat_id) DO NOTHING;
DROP TABLE chat_runs_staging;
SQL
fi

if [ -n "$FB_DUMP" ]; then
    echo "restoring feedback from $FB_DUMP"
    run_psql <<'SQL'
DROP TABLE IF EXISTS feedback_staging;
CREATE TABLE feedback_staging (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    chat_id TEXT,
    title TEXT,
    message TEXT,
    positive BOOLEAN,
    review BOOLEAN DEFAULT FALSE,
    liked BOOLEAN,
    created_at TIMESTAMPTZ
);
-- archive of raw pre-review-queue rows (recreated here if it was dropped)
CREATE TABLE IF NOT EXISTS feedback_legacy (LIKE feedback_staging INCLUDING ALL);
SQL
    sed 's/^INSERT INTO public\.feedback /INSERT INTO public.feedback_staging /' "$FB_DUMP" | run_psql
    run_psql <<'SQL'
INSERT INTO feedback_legacy SELECT * FROM feedback_staging ON CONFLICT (id) DO NOTHING;

-- Old design: one reaction row (liked, upserted) + appended comment rows per
-- (chat_id, session_id). Fold each group into one new-format review; rows
-- from the end-user widget (review = false) or missing either key stay in
-- feedback_legacy only, awaiting the dedicated end-user feedback table.
INSERT INTO feedback (id, chat_id, session_id, liked, comments, created_at, updated_at)
SELECT
    min(id),
    chat_id,
    session_id,
    bool_or(liked) FILTER (WHERE liked IS NOT NULL),
    coalesce(
        jsonb_agg(
            jsonb_build_object('title', title, 'message', message, 'positive', positive)
            ORDER BY created_at
        ) FILTER (WHERE message IS NOT NULL),
        '[]'::jsonb
    ),
    min(created_at),
    max(created_at)
FROM feedback_staging
WHERE review AND chat_id IS NOT NULL AND session_id IS NOT NULL
GROUP BY chat_id, session_id
ON CONFLICT (chat_id, session_id) DO NOTHING;
DROP TABLE feedback_staging;
SQL
fi

run_psql <<'SQL'
SELECT (SELECT count(*) FROM chat_runs) AS chat_runs,
       (SELECT count(*) FROM feedback)  AS reviews,
       (SELECT count(*) FROM feedback_legacy) AS legacy_rows;
SQL
