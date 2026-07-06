-- Vector index for embedding similarity search (tune lists after large ingests).
CREATE INDEX IF NOT EXISTS books_embedding_idx
    ON books USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Chat runs are loaded per session, newest first.
CREATE INDEX IF NOT EXISTS chat_runs_session_idx
    ON chat_runs (session_id, created_at);
