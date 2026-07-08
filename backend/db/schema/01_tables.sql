-- Books table (embedding width must match OPENAI_EMBEDDING_DIMENSIONS / init docs).
CREATE TABLE IF NOT EXISTS books (
    isbn13 TEXT PRIMARY KEY,
    isbn10 TEXT,
    title TEXT NOT NULL,
    authors TEXT,
    categories TEXT,
    genre TEXT,
    description TEXT,
    published_year INTEGER,
    average_rating DOUBLE PRECISION,
    num_pages INTEGER,
    ratings_count INTEGER,
    thumbnail TEXT,
    title_and_subtiles TEXT,
    is_children BOOLEAN DEFAULT FALSE,
    embedding VECTOR(1024)
);

-- Chat run records: one row per orchestrated chat turn.
-- Envelopes stored as JSONB (queryable via -> / ->>), hot stats promoted to columns.
-- liked: NULL = no feedback yet, TRUE = liked, FALSE = disliked.
CREATE TABLE IF NOT EXISTS chat_runs (
    chat_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_message TEXT,
    ok BOOLEAN,
    runtime_error TEXT,
    duration_s DOUBLE PRECISION,
    total_tokens INTEGER,
    orchestration JSONB,
    liked BOOLEAN
);

-- Standalone feedback / bug reports. chat_id and session_id are both
-- optional and unenforced (no FK) — a report can reference an in-flight
-- chat_id before its chat_runs row exists, an in-progress session with no
-- chat_id yet, or neither (a general bug report). id gets its own
-- independently generated key since chat_id/session_id may be NULL.
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    chat_id TEXT,
    title TEXT,
    message TEXT NOT NULL,
    positive BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
