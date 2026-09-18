# Database strategy — Neon instead of Cloud SQL

> **Companion to [deployment.md](deployment.md)**, which is written for Cloud SQL.
> This file replaces its **Stage 3** entirely and adjusts a few flags in Stages 2,
> 4 and 6. **Stage 1 is unaffected** — the container work is already committed
> (`151fa88`) and is correct either way.
>
> Verified against the code on 2026-09-17. Nothing here is guesswork about how
> the driver behaves; the two claims that usually get this wrong are checked
> against the installed SQLAlchemy 2.0.43 and asyncpg 0.29.0 and noted as such.

---

## Why

### The cost

Cloud SQL has no free tier and cannot scale to zero. The smallest instance that
runs this demo (`db-g1-small`) costs roughly **$28/month to sit idle**, which for
a portfolio demo that gets opened a few times a week is the entire bill.

Neon is managed Postgres with a free tier and **autosuspend** — the compute stops
when nobody is connected, so an idle week costs nothing. The database is **84 MB**
(measured, see below), comfortably inside the free tier's storage.

| Table | Size |
|---|---|
| `books` | 76 MB |
| `chat_runs` | 104 kB |
| `feedback` | 24 kB |
| `test_runs` | 16 kB |
| **total** | **84 MB** |

### Why not SQLite in the container

This was the obvious cheaper idea and it does not survive contact with the query
layer. **Four of the six registered nodes are built on a Postgres extension:**

| Node | Depends on | SQLite equivalent |
|---|---|---|
| `Retrieve_by_Title` | `similarity()` — pg_trgm | **none** |
| `Retrieve_by_Author` | `word_similarity()` — pg_trgm | **none** |
| `Retrieve_by_Lexical_Traits` | `to_tsvector` + GIN | FTS5 — different API |
| `Analyze_Similar_Books` | pgvector `cosine_distance` + ivfflat | sqlite-vec, or numpy |
| `Retrieve_by_Numeric_Traits` | plain predicates | ✅ portable |
| `Combine_Intersect` | CTE union/intersect | ✅ portable |

Two of those have decent answers — vector search over 5,197 × 1024 floats is
21 MB in memory and a brute-force matvec would be *more* accurate than the
current `lists=100` ivfflat index, and FTS5 is a real full-text engine.

**Trigram has no answer.** SQLite has no `similarity()`. The options are a Python
UDF (runs per row, through the interpreter, can never use an index) or moving
fuzzy matching out of SQL into `rapidfuzz`. Both break `DeferredBookQuery`
composition: once the similar-books pool is a Python list instead of a subquery,
`Combine_Intersect` cannot `compose()` against it, and "books like Dune under 300
pages" stops keeping cosine order — which `db/stores/deferred_query.py` documents
as the specific payoff of the current design. Three test files also assert
compiled SQL, and `tests/unit/db/stores/test_lexical_query.py` diffs SQLAlchemy's
output against the DDL in `02_indexes.sql`.

So it is not a driver swap; it is a rewrite of `book_store.py`,
`deferred_query.py`, the models, the schema and their tests.

### Why not move `chat_runs` to a bucket

Also considered, also rejected — on arithmetic. Those tables are **144 kB of an
84 MB database**, so moving them saves nothing on the bill, while
`ChatRunStore.get_all`'s "least-reviewed first" ordering (an outer join plus a
group-by) and the `test_runs ⋈ chat_runs` join behind `make suite-reports` both
become Python loops over downloaded objects. CLAUDE.md calls that second one the
project's golden-test mechanism.

The half that is cheap to move is the half that costs nothing to keep. The half
that costs money is the half that cannot move.

### What Neon keeps

pgvector, pg_trgm, full-text search, JSONB, and every line of the query layer.
**No application code changes** beyond the two connection fixes below — which are
small, and which you want regardless.

---

## Where this slots into the runbook

| deployment.md stage | Status under Neon |
|---|---|
| **Stage 1** — container | ✅ Unchanged, already committed |
| **Stage 2** — Cloud Run | Small edits: drop one API, add real env vars, add the probe |
| **Stage 3** — Cloud SQL | ❌ **Replaced by this document** |
| **Stage 4** — security | One line removed (`roles/cloudsql.client`), one secret renamed |
| **Stage 5** — go public | Unchanged, plus a note on autosuspend in 5.3 |
| **Stage 6** — docs | The Infrastructure claims change target |

### Do this *before* Cloud Run, not after

Your original order put the database third because **Cloud SQL forced it there** —
it needed a GCP project, an enabled API and a socket mount, none of which exist
until Cloud Run does. Neon needs none of that. It is set up entirely from your
laptop.

Running it first buys three things:

- The **first Cloud Run revision is a working one**, with real credentials instead
  of placeholders. No "deploy broken, then reconnect" step.
- The `/ready` **startup probe can be on from the first deploy**, so a
  misconfigured revision never goes live.
- Cloud Run reaches Neon over ordinary TCP+TLS — **the same path your laptop
  uses**. If `make neon-cli` works locally, the deployed service will connect.
  The Cloud SQL socket path had no local equivalent to test against.

The safety property is unchanged: Cloud Run still deploys
`--no-allow-unauthenticated`, and only goes public in Stage 5.

---

## Step 1 — Two code changes and a comment

### 1a. `config/settings/sqlalchemy.py`

**The trap that costs an afternoon: SQLAlchemy's asyncpg dialect needs `ssl=`,
but Neon's dashboard hands you `?sslmode=require`.**

Verified in the installed packages:

- `PGDialect_asyncpg.create_connect_args` is literally `opts.update(url.query)` —
  every query parameter is forwarded to `asyncpg.connect()` as a **keyword
  argument**.
- `inspect.signature(asyncpg.connect)` has **`ssl`** and **no `sslmode`**.
  asyncpg reads `sslmode` only out of a DSN string it parses itself
  (`connect_utils` line 349), which is not the path SQLAlchemy takes.
- A bare string is what it wants: `connect_utils` line 494 is
  `if isinstance(ssl, (str, SSLMode)): sslmode = SSLMode.parse(ssl)`.

Paste Neon's URL as-is and you get, at connect time, not import time:

```
TypeError: connect() got an unexpected keyword argument 'sslmode'
```

Replace the whole file:

```python
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict
from config.constants import FilesLocationConstants


class SQLAlchemySettings(BaseSettings):
    """Connection and pool settings for the async SQLAlchemy engine (PostgreSQL + asyncpg)."""

    HOST: str
    PORT: int
    DB: str
    USER: str
    PASSWORD: str
    MIN_CONNECTIONS: int
    MAX_CONNECTIONS: int
    # asyncpg's own default, so an unset value connects exactly as it did before
    # this field existed. Neon needs `require`; the local compose container
    # serves no TLS and falls back to plaintext under `prefer`. The only field
    # here with a default, for that reason — it keeps every existing .env and
    # the CI env matrix working unchanged.
    SSL_MODE: str = "prefer"

    @property
    def sqlalchemy_url(self) -> str:
        """Async SQLAlchemy URL (postgresql+asyncpg).

        **`ssl=`, not `sslmode=`.** SQLAlchemy's asyncpg dialect passes every
        query parameter straight through to `asyncpg.connect()` as a keyword
        argument (`create_connect_args` is `opts.update(url.query)`), and
        asyncpg has `ssl` but no `sslmode` — it reads that spelling only from a
        DSN it parses itself. Neon's dashboard hands out a `?sslmode=require`
        URL, so pasting it here raises
        `TypeError: connect() got an unexpected keyword argument 'sslmode'`.

        Credentials are percent-encoded because the password is no longer ours
        to choose — Neon generates it. An unescaped `@` re-points the host
        (everything left of the *last* `@` is the userinfo) and a `/` truncates
        the database name, neither of which fails loudly; both read as a wrong
        password for as long as it takes to find.
        """
        user = quote_plus(self.USER)
        password = quote_plus(self.PASSWORD)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.HOST}:{self.PORT}/{self.DB}?ssl={self.SSL_MODE}"
        )

    model_config = SettingsConfigDict(
        env_file=FilesLocationConstants.ENV_FILE,
        env_prefix="POSTGRES_",
        env_file_encoding="utf-8",
        extra="ignore",
    )
```

Two things went away in that rewrite, both deliberately:

- **The `/cloudsql/` branch.** Nothing will ever set that host again, and
  CLAUDE.md rule 5 says removal is part of the change. It is three lines in git
  history if you want it back.
- **The deferred `quote_plus` item.** The old plan dodged the escaping bug by
  generating an alphanumeric password. That option is gone — Neon generates the
  password — so the fix is now cheaper than the workaround.

### 1b. `tests/unit/config/test_settings.py`

Delete the three tests that only exist for the removed branch —
`test_cloudsql_url_format`, `test_cloudsql_when_host_starts_with_cloudsql_prefix`,
and `test_tcp_when_host_does_not_start_with_cloudsql` (which existed only to
contrast with them). Fix `test_tcp_url_format`'s expected string to end
`?ssl=prefer`. Then add guards for both fixes:

```python
class TestSQLAlchemySettingsSsl:
    def test_ssl_mode_defaults_to_asyncpg_default(self):
        assert make_sqlalchemy().SSL_MODE == "prefer"

    def test_ssl_mode_reaches_the_url(self):
        assert "?ssl=require" in make_sqlalchemy(SSL_MODE="require").sqlalchemy_url

    def test_parameter_is_ssl_not_sslmode(self):
        # asyncpg.connect() takes `ssl=` and has no `sslmode` keyword, and
        # SQLAlchemy's dialect forwards query parameters to it verbatim.
        # Emitting `sslmode` — which is what Neon's dashboard hands you —
        # raises TypeError at connect time, so assert the spelling, not the value.
        url = make_sqlalchemy(SSL_MODE="require").sqlalchemy_url
        assert "sslmode=" not in url
        assert "ssl=require" in url


class TestSQLAlchemySettingsCredentialEscaping:
    def test_password_reserved_characters_are_escaped(self):
        # an unescaped '@' re-points the host: everything left of the LAST '@'
        # is the userinfo, so "p@ss" would make "ss@localhost" the authority
        s = make_sqlalchemy(PASSWORD="p@ss/word#1")
        assert "p%40ss%2Fword%231" in s.sqlalchemy_url
        assert "@localhost:5432/mydb" in s.sqlalchemy_url

    def test_ordinary_credentials_are_left_alone(self):
        # Neon's generated passwords are alphanumeric with underscores, which
        # must survive untouched — quote_plus does not escape '_'
        s = make_sqlalchemy(USER="neondb_owner", PASSWORD="npg_AbC123xyZ")
        assert "neondb_owner:npg_AbC123xyZ@" in s.sqlalchemy_url
```

### 1c. `db/async_engine.py` — two stale comments

Lines 31 and 36 say "optimized for Cloud SQL" and "Cloud SQL friendly". Say Neon.

**Do not remove `pool_pre_ping=True`.** It is already there and it is exactly what
an autosuspending database needs: it discards a connection that died during
suspend instead of handing a dead one to a request. It is the reason autosuspend
is invisible rather than a 500 on the first chat after a quiet hour.

### 1d. `config/.env.example`

```
# 'require' for Neon; 'prefer' (the default) for the local compose container
POSTGRES_SSL_MODE=prefer
```

Because the field has a default, **this does not break CI** the way a required
field would — `.github/workflows/ci.yml`'s env block needs no change.

---

## Step 2 — Create the Neon project

1. Sign up at **[neon.tech](https://neon.tech)** (GitHub or Google login).
2. Create a project named `book-recommender`, and set:
   - **Postgres 16** — matches your local `pgvector/pgvector:pg16` and psql 16.14,
     so no version skew
   - **Cloud provider: GCP**, **region: `us-central1`** — the same region Cloud
     Run uses, so the per-query round trip stays inside one datacenter
3. Neon creates a database `neondb` and a role `neondb_owner`, then shows a
   connection string.

### Take the direct endpoint, not the pooled one

Neon offers two hostnames and the dashboard often defaults to the pooled one:

| Hostname | Use it? |
|---|---|
| `ep-<name>-<id>.us-central1.gcp.neon.tech` | ✅ **this one** |
| `ep-<name>-<id>-`**`pooler`**`.us-central1.gcp.neon.tech` | ❌ |

The `-pooler` host is PgBouncer in transaction mode, which breaks asyncpg's
prepared-statement cache. SQLAlchemy already maintains its own pool
(`db/async_engine.py`), so the pooler would be a second pool solving a problem you
do not have, at the cost of a failure mode that only appears under load.

### Map it into `config/.env`

The string looks like this. Note there is **no port** — use the default 5432:

```
postgresql://neondb_owner:npg_XXXXXXXX@ep-cool-darkness-a1b2c3d4.us-central1.gcp.neon.tech/neondb?sslmode=require
```

```bash
POSTGRES_HOST=ep-cool-darkness-a1b2c3d4.us-central1.gcp.neon.tech
POSTGRES_PORT=5432
POSTGRES_DB=neondb
POSTGRES_USER=neondb_owner
POSTGRES_PASSWORD=npg_XXXXXXXX
POSTGRES_SSL_MODE=require
POSTGRES_MIN_CONNECTIONS=2
POSTGRES_MAX_CONNECTIONS=12

# operator credential for psql — used only by the Makefile targets below
NEON_URL=postgresql://neondb_owner:npg_XXXXXXXX@ep-cool-darkness-a1b2c3d4.us-central1.gcp.neon.tech/neondb?sslmode=require
```

`NEON_URL` keeps `sslmode=require`, and that is correct — **psql parses the DSN
itself**, so it wants the libpq spelling. Only asyncpg needs `ssl=`. The two
spellings living side by side in one file is confusing enough to be worth the
comment.

**Keep your local values.** You will switch back and forth; the simplest way is a
`config/.env.local` and a `config/.env.neon`, copying one over `config/.env`.
Verified: both are gitignored by the existing `config/.env*` rule
(`backend/.gitignore:9`), and `.dockerignore` / `.gcloudignore` both already
exclude `config/.env.*`.

---

## Step 3 — Makefile targets

Add to `backend/Makefile`, beside the existing `postgres-*` family:

```make
# -------------------
# Neon (managed Postgres)
# -------------------

# NEON_URL is the operator credential for psql, read from config/.env.
# Deliberately a SEPARATE variable from the POSTGRES_* app settings: these
# targets write, and a mistyped host should never be able to bootstrap the
# local container or production by accident.
NEON_URL ?= $(shell set -a; . $(ENV_FILE) 2>/dev/null; set +a; echo $$NEON_URL)

.PHONY: neon-guard
neon-guard:
	@test -n "$(NEON_URL)" || { echo "NEON_URL is not set — add it to config/.env"; exit 1; }

# psql shell on Neon:   make neon-cli
# one file or command:  make neon-cli ARGS="-f db/schema/migrations/xxx.sql"
.PHONY: neon-cli
neon-cli: neon-guard
	psql "$(NEON_URL)" $(ARGS)

# dump the local container's books table (data only, COPY format).
# No --column-inserts: 5,197 rows x 1024 floats as individual INSERTs would be
# enormous and slow to replay.
.PHONY: postgres-dump-books
postgres-dump-books:
	@mkdir -p $(MAKEFILE_DIR)data/backup
	set -a && . $(ENV_FILE) && set +a && \
	docker exec -i -e PGPASSWORD=$$POSTGRES_PASSWORD $(POSTGRES_CONTAINER) \
		pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB --table=books --data-only \
		> $(MAKEFILE_DIR)data/backup/books.sql
	@echo "books dumped to $(MAKEFILE_DIR)data/backup/books.sql"

# seed a fresh Neon database. THE ORDER IS LOAD-BEARING — see Step 5.
.PHONY: neon-bootstrap
neon-bootstrap: neon-guard
	psql "$(NEON_URL)" -v ON_ERROR_STOP=1 -f $(MAKEFILE_DIR)db/schema/00_extensions.sql
	psql "$(NEON_URL)" -v ON_ERROR_STOP=1 -f $(MAKEFILE_DIR)db/schema/01_tables.sql
	psql "$(NEON_URL)" -v ON_ERROR_STOP=1 -f $(MAKEFILE_DIR)data/backup/books.sql
	psql "$(NEON_URL)" -v ON_ERROR_STOP=1 -f $(MAKEFILE_DIR)db/schema/02_indexes.sql
	@echo "Neon bootstrapped."
```

`ON_ERROR_STOP=1` matters. Without it psql reports an error and keeps going, so a
failed `CREATE EXTENSION` would leave you loading 100 MB of books into a database
with no `vector` type and a confusing error at the end of it.

---

## Step 4 — Dump books from the local container

### Add a gitignore rule first

`backend/.gitignore:13` ignores `*backup.sql`, which covered the old
`data/backup/backup.sql` but **does not match `books.sql`** — so the dump is
committable as things stand, and GitHub rejects pushes over 100 MB. Add:

```
# Database dumps — books.sql is ~150MB of text-format vectors
data/backup/
```

### Then dump

```bash
cd backend
make postgres-start        # if it is not already up
make postgres-dump-books
ls -lh data/backup/books.sql    # expect ~100-150 MB
```

Text-format floats are much larger than their on-disk form, so a 76 MB table
dumps to well over 100 MB.

**Do this before anything else, even if you are not ready to deploy.** The local
container is currently the *only* copy of the embeddings — `data/backup/` is
empty, so the dump referenced in `Makefile:75` is already gone. Regenerating
5,197 embeddings costs real OpenAI spend, and `data/books.csv` has no vectors.

---

## Step 5 — Bootstrap, in this order

```bash
make neon-bootstrap
```

The ordering is not stylistic:

1. **`00_extensions.sql`** — `vector` and `pg_trgm`. Neon allows both without
   superuser, but nothing in the app creates them, and the books load fails
   without `vector` because the column type would not exist.
2. **`01_tables.sql`**
3. **Load `books.sql`**
4. **`02_indexes.sql` — last, deliberately.** `books_embedding_idx` is
   `ivfflat ... WITH (lists = 100)`, and ivfflat builds its centroids from the
   rows present **at creation time**. Built on an empty table it is useless and
   similarity recall degrades *silently* — you still get answers, just worse
   ones, with nothing in the logs. `books_search_idx` and `feedback_review_idx`
   also need their tables to exist.

Expect the books load to take a few minutes over TLS.

**No migration runner needed.** All seven files in `db/schema/migrations/` are
already folded into the base schema — `writer JSONB` is in `01_tables.sql`,
`books_search_idx` is in `02_indexes.sql`. A fresh database gets the current
schema from `00/01/02`; building a runner now is building for a caller that does
not exist. The durable rule: a schema change lands in `db/schema/0*.sql` **and** a
dated migration file, and the migration is applied with
`make neon-cli ARGS="-f db/schema/migrations/<file>.sql"`.

---

## Step 6 — Prove it locally

With `config/.env` pointing at Neon:

```bash
make dev
curl localhost:8000/ready     # -> 200, against Neon
```

Then send a real chat message and confirm book cards come back. This is the whole
point of doing the database first: **the exact code path Cloud Run will use**,
exercised where you can actually debug it.

### ✅ Checkpoint

```bash
make neon-cli ARGS='-c "\dx"'                         # vector, pg_trgm
make neon-cli ARGS='-c "SELECT count(*) FROM books;"' # 5197
make neon-cli ARGS='-c "\di"'                         # four indexes
make neon-cli ARGS='-c "SHOW max_connections;"'       # see Pool sizing
curl localhost:8000/ready                             # 200
```

Plus one real chat turn returning book cards. Then **switch `config/.env` back to
the local container** for day-to-day work — the Cloud Run deploy passes Neon
credentials explicitly, so the deployed service never depends on what your `.env`
happens to say.

---

## What changes in deployment.md's other stages

### Stage 2 — Cloud Run

**2.1** — drop `sqladmin.googleapis.com` from the `gcloud services enable` list.
There is no Cloud SQL instance to administer.

**2.2** — the deploy now carries real credentials and a startup probe. Set the
values first so no secret lands in shell history:

```bash
NEON_HOST=ep-cool-darkness-a1b2c3d4.us-central1.gcp.neon.tech
NEON_USER=neondb_owner
NEON_DB=neondb
read -rs -p "Neon password: "   NEON_PW;    echo
read -rs -p "OpenAI API key: "  OPENAI_KEY; echo
```

```bash
gcloud run deploy book-rec-api \
  --source=backend/ --region=$REGION --no-allow-unauthenticated \
  --cpu=1 --memory=1Gi --cpu-boost --timeout=300 \
  --min-instances=0 --max-instances=3 --concurrency=5 \
  --startup-probe=httpGet.path=/ready,initialDelaySeconds=5,timeoutSeconds=5,periodSeconds=5,failureThreshold=6 \
  --set-env-vars="^@^APP_NAME=book-recommender-backend@APP_ENVIRONMENT=production@APP_ALLOW_ORIGINS=http://localhost:3000@POSTGRES_HOST=$NEON_HOST@POSTGRES_PORT=5432@POSTGRES_DB=$NEON_DB@POSTGRES_USER=$NEON_USER@POSTGRES_PASSWORD=$NEON_PW@POSTGRES_SSL_MODE=require@POSTGRES_MIN_CONNECTIONS=2@POSTGRES_MAX_CONNECTIONS=12@OPENAI_API_KEY=$OPENAI_KEY@OPENAI_BASE_MODEL=gpt-4.1-mini@OPENAI_TOKENIZER_ENCODING=o200k_base@OPENAI_EMBEDDING_MODEL=text-embedding-3-large@OPENAI_EMBEDDING_DIMENSIONS=1024@OPENAI_MAX_CONCURRENCY=10"
```

- **`^@^` is still load-bearing** — it changes gcloud's list delimiter from `,` to
  `@`, and `APP_ALLOW_ORIGINS` gains a comma in Stage 5.
- **`POSTGRES_SSL_MODE=require` is not optional.** Neon refuses plaintext. The
  default `prefer` would negotiate TLS anyway, but it *silently falls back* to
  plaintext if TLS fails, and you want an error instead.
- The two secrets are plain env vars here, readable by anyone with console access.
  Stage 4.5 moves them to Secret Manager; that section is self-contained if you
  want it sooner.

**The `/ready` startup probe earns its place.** Cloud Run's default check is
TCP-on-`$PORT`, and since `common/context.py:44-48` has `ping_services()`
commented out, a container with a wrong host binds the port and goes live serving
500s on every chat. `/ready` runs a real `SELECT 1` (`health.py:20-46` already
returns 503 on failure), so a bad host, wrong password or missing `ssl=require`
means the revision **never goes live and the previous one keeps serving**.

Do **not** re-enable `ping_services()` instead — it also calls
`OpenAIClient.ping()`, a billed API call on every cold start. Nothing else calls
it; delete it with the dead comment.

No liveness probe: a transient blip would kill healthy containers mid-stream, and
Neon resuming from autosuspend looks exactly like one.

### Stage 4 — security

**4.5** — remove the `roles/cloudsql.client` binding; the database is reached over
ordinary TLS, so the service account needs nothing but secret access. That is a
feature: it becomes the least-privileged identity in the project. The secret is
still called `postgres-password`; it just holds `$NEON_PW`.

**4.6** — the Neon host, user and database are plain `--set-env-vars` values and
belong in the `make deploy` recipe; the password and API key come from
`--set-secrets` by then, so the target holds no credential and is safe to commit.

**Stage 4 checkpoint** — read back with
`make neon-cli ARGS='-c "SELECT chat_id, user_message FROM chat_runs ORDER BY created_at DESC LIMIT 5;"'`.

### Stage 5 — go public

**5.3** — `--min-instances=1` now buys two things, not one. A warm instance also
holds a connection open, which stops Neon autosuspending, so the first chat after
a quiet hour skips both the container cold start *and* the database resume. The
trade is that it also stops your free-tier compute hours from idling — watch usage
for a week before leaving it on.

### Stage 6 — docs

`CLAUDE.md`'s Infrastructure section currently says "**Database**: Cloud SQL
(PostgreSQL)". It should name Neon and its `us-central1` GCP region. Check
`backend/db/README.md` too — the connection story now has two targets (local
container, Neon) selected by `config/.env`.

---

## Pool sizing

The binding constraint is easy to miss. `get_sqlalchemy_session`
(`app/api/dependencies.py:42-53`) is a **`yield` dependency**, so its connection
is held for the *entire SSE stream*, not per query — and once Stage 4 uncomments
the recorder, `record_chat_run` opens a **second, independent** session while the
first is still open. Peak is **2 connections per in-flight turn**.

| Knob | Value | Why |
|---|---|---|
| `--concurrency` | 5 | 5 turns × 2 conns = 10 |
| `--max-instances` | 3 | ~15 concurrent turns; under the 500 RPM tier in `docs/backlog.md:52-58` |
| `POSTGRES_MIN_CONNECTIONS` | 2 | `pool_size` |
| `POSTGRES_MAX_CONNECTIONS` | 12 | pool 2 + overflow 10 (`db/async_engine.py:32-34`) |
| Worst case | 36 | 3 × 12 |

The shipped defaults (`.env.example:18-19`, MIN=5/MAX=20) are **per instance** — at
3 instances that is 60. Both are env-driven, so this is config, not code. Check
the real ceiling with `make neon-cli ARGS='-c "SHOW max_connections;"'`; Neon sets
it from compute size, and the smallest tier still allows comfortably more than 36.

---

## Deferred, with reasons

- **`lists = 100` is wrong for 5,197 rows.** pgvector's guidance is `rows/1000` ≈ 5.
  At 100 each list holds ~52 rows and the default `ivfflat.probes = 1` scans one —
  recalling ~1% of the table per query. At this size an exact scan is single-digit
  milliseconds anyway. **Keep 100 for parity with local** (changing it changes eval
  results) and treat it as a recall question, not a deploy action.
- **`verify-full` instead of `require`.** `require` encrypts but does not verify
  the certificate, so it does not stop an active man-in-the-middle. `verify-full`
  does, Neon's certificates are from a public CA, and `python:3.12-slim` ships the
  CA bundle to validate against — so it is a one-word change to
  `POSTGRES_SSL_MODE`. Left until after the deploy works, because a certificate
  problem and a connection problem look identical from outside and you do not want
  to debug both at once.
- **pandas is never imported at runtime** (verified by grep across `app/ common/
  db/ clients/ config/ airglider/`). It pulls ~100MB with numpy for evals and
  notebooks only. Moving it to the dev group is correct but churns `poetry.lock` —
  do it after the image is proven.

---

## Risks

- **The free tier is a real ceiling.** Neon's free plan caps storage (~0.5 GB —
  you are at 84 MB) and monthly compute hours. Check the current limits when you
  sign up rather than trusting this line, and watch usage for the first week. A
  paid tier is still far below Cloud SQL, so the failure mode is a small bill, not
  an outage — set a billing alert anyway.
- **Autosuspend adds latency to the first query after idle**, on top of the Cloud
  Run cold start you already accepted. `pool_pre_ping=True` makes it *correct*; it
  does not make it *fast*. Stage 5.3 is the lever.
- **Neon is a third party**, not GCP. It runs in GCP `us-central1`, but it is
  another account, another status page and another thing that can change its free
  tier. The mitigation is that nothing is locked in: it is stock Postgres 16, so
  moving to Cloud SQL later is `pg_dump` plus five env vars.
- **The books seed depends on the local container staying populated** until Neon
  is bootstrapped. Once it is, you have a second copy — the first time this
  project has had one.
