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
    sse_events JSONB
);

-- Links an eval-suite case to the chat run it produced. Written by
-- evals/run_suites.py after a suite run; joined with chat_runs by the
-- evals report script (evals/report.py). CASCADE: wiping chat_runs
-- between eval campaigns auto-cleans these rows.
CREATE TABLE IF NOT EXISTS test_runs (
    chat_id TEXT PRIMARY KEY REFERENCES chat_runs(chat_id) ON DELETE CASCADE,
    suite_name TEXT NOT NULL,
    suite_case_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reviews from the internal /review page: one row per (chat_id, session_id),
-- where session_id is the *reviewing* session, not the session that produced
-- the run. A session re-submitting replaces its review in place (see unique
-- index) rather than appending; a different session appends a new review.
-- liked: the reviewer's overall like/dislike of the run (optional).
-- comments: JSONB list of {title, message, positive} observations, replaced
-- whole on each submit.
-- chat_id CASCADEs from chat_runs: the review page only lists runs already
-- persisted there, so a review's target run always exists by submit time —
-- wiping chat_runs cleans up its reviews too.
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chat_runs(chat_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    liked BOOLEAN,
    comments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feedback_liked_or_comments CHECK (liked IS NOT NULL OR jsonb_array_length(comments) > 0)
);
