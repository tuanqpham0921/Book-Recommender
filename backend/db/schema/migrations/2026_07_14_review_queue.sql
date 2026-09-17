-- Shared review queue migration (2026-07-14).
-- feedback becomes review-only: one row per (chat_id, reviewing session_id),
-- upserted whole, with comments as a JSONB list. chat_runs drops liked and
-- reviewed — a run's review count is derived from feedback rows, not stored.
-- The old mixed report/reaction table is kept as feedback_legacy (its rows
-- don't fit the new shape); drop it manually once you no longer need them.
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_07_14_review_queue.sql
BEGIN;

ALTER TABLE feedback RENAME TO feedback_legacy;
ALTER INDEX IF EXISTS feedback_reviewer_reaction_idx RENAME TO feedback_legacy_reviewer_reaction_idx;

CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    liked BOOLEAN,
    comments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feedback_liked_or_comments CHECK (liked IS NOT NULL OR jsonb_array_length(comments) > 0)
);

CREATE UNIQUE INDEX feedback_review_idx
    ON feedback (chat_id, session_id);

ALTER TABLE chat_runs
    DROP COLUMN IF EXISTS liked,
    DROP COLUMN IF EXISTS reviewed;

COMMIT;
