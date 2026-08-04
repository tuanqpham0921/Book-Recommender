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
  `base_store.py` (shared execute helpers), `book_store.py` (primary store: title
  search + embeddings, plus the deferred-query API below), `chat_run_store.py`
  (review queue, ordered least-reviewed-first), `feedback_store.py` (review upsert).
- **Deferred queries** (`deferred_query.py` + the `build_*_query` / `build_count` /
  `compose` / `build_materialize` family in `utils.py`). Retrieval nodes do not
  fetch rows: `BookStore.title_query()` builds a statement, `count()` runs only a
  `COUNT` over it, and the statement itself rides downstream on the node's output.
  `compose()` folds several of them into one `WITH` clause (`"or"` pools, `"and"`
  intersects, both deduped by isbn13 in SQL), and `materialize()` is the single
  place rows are fetched — at the end of the plan. `preview()` is the exception
  that proves the rule: it returns `(total, rows)` for the UI's sample cards
  using `count(*) OVER ()`, so the count and the handful of books shown under it
  come from **one** round trip and cannot disagree. A `DeferredBookQuery` selects
  isbn13 (plus an optional `score`) and carries **no LIMIT and no ORDER BY**; that
  is what makes two of them composable, so don't add either in a builder. See
  docs/design/execution-pipeline-v1.md.
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
