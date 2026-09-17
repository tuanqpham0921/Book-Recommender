-- feedback FK migration (2026-07-15): chat_id becomes a real foreign key
-- into chat_runs, ON DELETE CASCADE — wiping a chat_runs row (or the whole
-- table, as postgres-clear-chat-runs / postgres-logs-clear do) now also
-- removes its reviews, same as test_runs already does.
--
-- Any feedback rows whose chat_id has no matching chat_runs row (e.g. an
-- old dev database that had chat_runs cleared without also clearing
-- feedback) would violate the new constraint, so they're deleted first —
-- a no-op on a database where every review's run still exists.
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_07_15_feedback_chat_id_fk.sql
BEGIN;

DELETE FROM feedback f
WHERE NOT EXISTS (SELECT 1 FROM chat_runs c WHERE c.chat_id = f.chat_id);

ALTER TABLE feedback
    ADD CONSTRAINT feedback_chat_id_fkey
    FOREIGN KEY (chat_id) REFERENCES chat_runs(chat_id) ON DELETE CASCADE;

COMMIT;
