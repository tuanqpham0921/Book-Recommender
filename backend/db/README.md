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
  `base_store.py` (shared execute helpers), `book_store.py` (primary store: title /
  author / ISBN / filter search + embeddings), `chat_run_store.py` (review queue,
  ordered least-reviewed-first), `feedback_store.py` (review upsert).
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
