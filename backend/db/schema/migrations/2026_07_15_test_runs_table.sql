-- test_runs migration (2026-07-15): suite linkage moves off chat_runs.
-- Supersedes 2026_07_15_chat_runs_suite_columns.sql / the backfill: instead
-- of suite_name/suite_case_id columns on chat_runs, each suite-produced run
-- gets one row in test_runs (chat_id FK -> chat_runs, ON DELETE CASCADE so
-- wiping chat_runs between eval campaigns auto-cleans it). Existing linkage
-- in the old columns is copied over before the columns are dropped, so this
-- is safe to run on a database that had the previous migrations applied —
-- and on a fresh one (the copy step no-ops when the columns don't exist is
-- NOT true in plain SQL, so fresh databases should init from db/schema/
-- instead of running this).
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_07_15_test_runs_table.sql
BEGIN;

CREATE TABLE IF NOT EXISTS test_runs (
    chat_id TEXT PRIMARY KEY REFERENCES chat_runs(chat_id) ON DELETE CASCADE,
    suite_name TEXT NOT NULL,
    suite_case_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO test_runs (chat_id, suite_name, suite_case_id)
SELECT chat_id, suite_name, suite_case_id
FROM chat_runs
WHERE suite_name IS NOT NULL AND suite_case_id IS NOT NULL
ON CONFLICT (chat_id) DO NOTHING;

ALTER TABLE chat_runs
    DROP COLUMN IF EXISTS suite_name,
    DROP COLUMN IF EXISTS suite_case_id;

COMMIT;
