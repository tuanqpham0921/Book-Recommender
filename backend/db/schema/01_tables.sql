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
    duration_s DOUBLE PRECISION,
    total_tokens INTEGER,
    orchestration JSONB,
    mermaid TEXT,
    liked BOOLEAN,
    comment TEXT
);
