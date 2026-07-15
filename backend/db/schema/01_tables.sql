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
-- Review state lives entirely in the feedback table: a run's review count is
-- derived by counting its feedback rows, never stored here.
CREATE TABLE IF NOT EXISTS chat_runs (
    chat_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_message TEXT,
    ok BOOLEAN,
    runtime_error TEXT,
    duration_s DOUBLE PRECISION,
    total_tokens INTEGER,
    mermaid TEXT,
    planner JSONB,
    tasks JSONB,
    sse_events JSONB,
    -- set only for runs produced by evals/run_suites.py:
    -- which suite file (stem, e.g. 'query_suite') and which entry id in it.
    -- NULL for real user chats, so evals can filter on suite_name IS NULL.
    suite_name TEXT,
    suite_case_id INTEGER
);

-- Reviews from the internal /review page: one row per (chat_id, session_id),
-- where session_id is the *reviewing* session, not the session that produced
-- the run. A session re-submitting replaces its review in place (see unique
-- index) rather than appending; a different session appends a new review.
-- liked: the reviewer's overall like/dislike of the run (optional).
-- comments: JSONB list of {title, message, positive} observations, replaced
-- whole on each submit.
-- chat_id is unenforced (no FK) so a review can reference a run whose row
-- hasn't been recorded yet. End-user feedback (live-chat widget) no longer
-- writes here — it gets its own dedicated table later.
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    liked BOOLEAN,
    comments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feedback_liked_or_comments CHECK (liked IS NOT NULL OR jsonb_array_length(comments) > 0)
);
