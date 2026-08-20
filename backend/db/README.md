# backend/db

Async SQLAlchemy database layer for PostgreSQL + pgvector.

## Layout

- `async_engine.py` — the shared async engine/session factory. Create sessions from
  here; the engine is closed on app shutdown (don't create ad-hoc engines).
- `schema/` — schema is created by **raw SQL, in order**: extensions → tables →
  indexes. `models.py` holds the SQLAlchemy ORM models, but
  `Base.metadata.create_all` is *not* how tables come to exist — which is why
  `index=True` flags on models do nothing (docs/backlog.md, Performance).
- `stores/` — repository pattern; routes/workflows never touch sessions directly.
  `base_store.py` (shared execute helpers), `book_store.py` (primary store: the
  deferred-query API below, plus the module-level `embedding_search_stmt` — a
  pure builder rather than a store method, so a caller can record its SQL
  before running it; `BookStore.search_similar(stmt)` is the execute half),
  `chat_run_store.py` (review queue, ordered least-reviewed-first),
  `feedback_store.py` (review upsert).
- **Deferred queries** (`deferred_query.py`). Retrieval nodes do not fetch rows:
  `BookStore.title_query()` / `author_query()` build a statement, `count()` runs only a `COUNT`
  over it, and the statement itself rides downstream on the node's output.
  The split is two questions: **building from a dimension and executing live on
  the store** (they need the model and the session — `filter_query()` is on that
  side too: narrowing an existing query by `BookMetadataFilter` bounds needs the
  model's columns, and it hands back another deferred query rather than rows);
  **everything derivable from
  an already-built query lives on `DeferredBookQuery` itself** — `count_stmt()`,
  `materialize_stmt()`, and `DeferredBookQuery.compose()`, which folds several
  queries into one `WITH` clause (`"or"` pools, `"and"` intersects, both deduped
  by isbn13 in SQL). `materialize()` is the single place rows are fetched — at
  the end of the plan (the UI's sample cards are a small `materialize()` call
  too, streamed and dropped — see `BookWorkflow.preview_books`). A
  `DeferredBookQuery` selects isbn13 (plus an optional `score`) and carries
  **no LIMIT and no ORDER BY**; that is what makes two of them composable, so
  don't add either when building one. See docs/design/execution-pipeline-v1.md.
- `bootstrap.py`, `readiness.py` — startup schema checks backing `GET /ready`.
- `ingestion/` — populates `books` from `data/books.csv`. **Legacy, ignore**: old
  Workflow/@task patterns; don't refactor it or model new code on it.

## Tables

| Table | Purpose |
|---|---|
| `books` | Book catalog + pgvector embeddings |
| `chat_runs` | One row per chat turn: user/assistant messages, planner/tasks JSONB, promoted stats (duration, tokens). PK `chat_id` |
| `feedback` | One review per (chat_id, session_id), upserted whole. FK `chat_id` → `chat_runs`, CASCADE |
| `test_runs` | Eval bookkeeping: chat_id FK → `chat_runs` (CASCADE — deleting chat_runs takes test_runs with it) + suite name + case id |

## Local dev

```bash
make postgres-start     # Docker Compose PostgreSQL
make postgres-restore   # load data/backup.sql
make postgres-cli       # psql shell
make postgres-stop
```
