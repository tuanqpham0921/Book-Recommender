-- Suite tracking migration (2026-07-15).
-- chat_runs gains two nullable columns identifying the query-suite case that
-- produced a run: suite_name is the suite file stem (e.g. 'query_suite',
-- 'query_suite_adversarial') and suite_case_id is the entry's id inside that
-- file. Real user chats leave both NULL, so evals can filter with
-- suite_name IS NULL instead of relying on the session id prefix.
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_07_15_chat_runs_suite_columns.sql
BEGIN;

ALTER TABLE chat_runs
    ADD COLUMN IF NOT EXISTS suite_name TEXT,
    ADD COLUMN IF NOT EXISTS suite_case_id INTEGER;

COMMIT;
