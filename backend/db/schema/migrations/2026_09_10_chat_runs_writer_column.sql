-- Reply-stage envelope migration (2026-09-10).
-- chat_runs gains a third JSONB envelope beside planner and tasks: writer, the
-- record of the once-per-turn reply stage (GenerateRecommendationsExecutor).
-- Stored in full rather than as its to_summary() — the summary is two counts,
-- and the prose only ever existed as SSE deltas, so this is the only copy of
-- what the turn actually said. Runs before the stage existed leave it NULL.
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_09_10_chat_runs_writer_column.sql
BEGIN;

ALTER TABLE chat_runs
    ADD COLUMN IF NOT EXISTS writer JSONB;

COMMIT;
