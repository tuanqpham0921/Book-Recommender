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
-- review: TRUE when filed from the internal /review page, FALSE when filed
-- by an end user from the live chat's feedback widget.
-- liked: a reviewer's like/dislike reaction to one run, independent of the
-- run's own chat_runs.liked (the original end-user's reaction) — a reviewer
-- may disagree with the user, or review a run from a different session than
-- the one it was created in. NULL for ordinary issue/praise reports; one row
-- per (chat_id, session_id) carries a non-null liked (see unique index
-- below), upserted in place rather than appended like the report log.
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    chat_id TEXT,
    title TEXT,
    message TEXT,
    positive BOOLEAN,
    review BOOLEAN NOT NULL DEFAULT FALSE,
    liked BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feedback_message_or_liked CHECK (message IS NOT NULL OR liked IS NOT NULL)
);
