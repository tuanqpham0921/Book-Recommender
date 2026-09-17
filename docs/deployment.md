# Deploying Book-Recommender to GCP — staged runbook

## Context

The goal is a public demo: anyone opens `tuanqpham0921.web.app` and chats. Today
only the frontend is deployed; the backend is reached through an ngrok tunnel
(`make tunnel`), which is why `frontend/src/api.js:34` still sends an
`ngrok-skip-browser-warning` header on every request.

**The Cloud Run path the docs describe does not exist.** `README.md:52-56` and
`CLAUDE.md`'s Infrastructure section both say `gcloud builds submit --config
cloudbuild.yaml` works. There is no `cloudbuild.yaml` in the repo, and
`backend/Dockerfile` **cannot build**: `COPY ../pyproject.toml` (line 7) and
`COPY ../app` (line 17) reach outside the build context, which Docker rejects.
Even fixed, it copies only `app/` while `app/main.py` needs `config`, `common`,
`db`, `clients` and `airglider`.

Stages run in your order — Dockerfile, Cloud Run, Cloud SQL, then security —
with one adjustment that makes that order safe: **Stage 2 deploys the service
private** (`--no-allow-unauthenticated`). It only becomes public in Stage 5,
after the security work. So you can go one stage at a time without ever having
an unprotected endpoint live.

### Verified state (checked directly, 2026-09-17)

| Thing | State |
|---|---|
| Working tree | Clean. No merge in progress |
| `gcloud config project` | **`tuanqpham-508821` — the wrong project.** Stage 2 sets `tuanqpham0921` (number 286869228046, which matches the old Cloud Run URL commented at `api.js:2`) |
| `cloud-sql-proxy` | **Not installed.** Stage 3 installs it |
| Local tooling | docker 28.3.0, psql 16.14, firebase 15.30.1, gcloud 532.0.0 — all fine |
| Books data | **Live in the local `book-rec-postgres` container: 5,197 rows, all 5,197 embedded.** `data/backup/` is **empty** — the dump referenced in `Makefile:75` is gone. Stage 3 regenerates it with `pg_dump` |
| `chat_runs` locally | 3 rows |

### Two things worth knowing before you start

**Nothing is recorded in production today.** `app/orchestration/run_recorder.py`'s
docstring says "everything else (prod): database only — Cloud Run's filesystem is
ephemeral", but the database write at lines 186-188 is commented out, and the
file-writing branch above it is gated on `app_env == "development"`. So a
deployed instance writes **no file and no row**: no evals, no review page, no
debugging. Stage 4 uncomments it — deliberately in the same stage as the auth
gate, because that write is also what makes `/chat_runs` worth protecting.

**`config/settings/sqlalchemy.py:21` interpolates user and password into the URL
unescaped.** A password containing `@ : / # ?` silently corrupts the connection
string. Stage 3 generates an alphanumeric-only password to sidestep it, and logs
the `quote_plus` fix in the backlog rather than building around it now.

---

# Stage 1 — Make the container build

Nothing here touches GCP. Ends with the image serving real traffic locally.

### 1.1 Replace `backend/Dockerfile`

Build context is `backend/`. Each point fixes a specific current defect:

- **Multi-stage**, `python:3.12-slim`. Your poetry venv is already
  `book-rec-i6cZOUnN-py3.12`; CI and pyright say 3.11. Bump
  `.github/actions/setup/action.yml` to `python-version: "3.12"` and
  `pyproject.toml`'s `pythonVersion = "3.12"` so tested == shipped. **Leave
  `python = "^3.11"` alone** — 3.12 satisfies that range, so `poetry.lock`'s
  content-hash stays valid and you avoid a 357KB lock diff.
- **`poetry install --only main --no-root`.** `--no-root` skips installing the
  project as a package, which sidesteps `pyproject.toml:6-12` omitting `clients`
  from `packages` even though `common/context.py:6` imports it. The app runs
  from source with `WORKDIR` on `sys.path`, exactly like `make dev`.
- **Copy an explicit whitelist**, not `COPY . .`: `airglider app clients common
  config db`. A directory copy carries the five prompt `.txt` templates that
  `app/common/prompt_loader.py:12` reads at runtime — a `COPY **/*.py` pattern
  would silently drop them and fail on first request rather than at boot.
- **Pre-warm the tiktoken cache.** `clients/openai_client.py:55` calls
  `token_count()` on the embeddings path; tiktoken lazily downloads a BPE file
  from `openaipublic.blob.core.windows.net` on first use. With min-instances=0
  that fetch lands on a user-facing cold start. Set
  `ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken` and bake both encodings at build:
  `RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"`
  (`cl100k_base` backs `text-embedding-3-large`; `o200k_base` is
  `OPENAI_TOKENIZER_ENCODING`).
- **Honor `$PORT`** — Cloud Run injects it; the current CMD hardcodes 8000. Use
  the shell form so it expands, with `exec` so uvicorn is PID 1 and Cloud Run's
  SIGTERM reaches it (in-flight SSE streams then close cleanly):
  `CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`.
  One worker, no `--workers` — Cloud Run is one process per container and scales
  by instance.
- Run as a non-root user.
- No `apt-get` layer: `asyncpg`, `pandas`, `tiktoken` all ship manylinux wheels
  and `pgvector` is pure Python.

### 1.2 Add `backend/.dockerignore` **and** `backend/.gcloudignore`

Two files, because **they use different matching rules** and getting this wrong
is the most common way to leak a secret or upload 220MB.

- `.dockerignore` — Docker's matcher does not cross `/`, so bare `*` plus
  `!name` negations work.
- `.gcloudignore` — gitignore semantics, where an unanchored `*` re-matches
  nested paths and kills your negations. **Anchor every line with a leading
  `/`.** Keep `Dockerfile` in this one: Cloud Build needs it inside the uploaded
  tarball, whereas local `docker build` reads it out of band.

Both must exclude `config/.env` — otherwise your real secrets get baked into the
image. Both exclude `logs/`, `data/`, `evals/` (145MB), `playground/`, `tests/`,
`.venv`, `__pycache__`. Without `.gcloudignore`, `gcloud` uploads ~3,900 files
per deploy, and if the file is absent while `.gitignore` exists, gcloud *writes*
a generated `.gcloudignore` into your repo.

### 1.3 Delete the dead entrypoints

Rule 5 (removal is part of the change):

- `app/main.py:74-91` — the `if __name__ == "__main__"` block labelled "Cloud Run
  entry point" is unreachable from both `make dev` and the container. Delete it
  and the now-unused `import os` on line 1. The new `CMD` replaces it.
- `pyproject.toml:63-65` — `[tool.poetry.scripts]` declares
  `ingestion = "db.ingestion.main:main"` (**verified: the module does not
  exist**) and `app = "app.main:main"` (`app/main.py` has no `main()`). Both
  dead; delete the block and the `ingestion` target at `Makefile:24`.
- Add `{ include = "clients" }` to `packages` while you are in the file.

**Leave `make dev` alone.** It has no `--port`, so it defaults to 8000, which is
what `frontend/.env` and the README expect. One mechanism (uvicorn), two
invocations.

### ✅ Stage 1 checkpoint

```bash
cd backend
docker build -t book-rec-api .
docker run --rm --network host -e PORT=8080 --env-file config/.env book-rec-api
curl localhost:8080/ping     # -> {"status":"ok",...}
curl localhost:8080/ready    # -> 200, proves it reached the local postgres
```
Then send one real chat message and confirm SSE streams. Also
`make tests-all && make typecheck` after the pyproject/CI edits.

---

# Stage 2 — Get it onto Cloud Run (private)

No database yet, so `/ready` will fail — that is expected and fine. This stage
proves build, push, boot and `$PORT` only.

### 2.1 Point gcloud at the right project

Currently set to `tuanqpham-508821`. The Firebase project — and the old Cloud Run
service — live in `tuanqpham0921`.

```bash
export PROJECT=tuanqpham0921 REGION=us-central1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com --project=$PROJECT
```

### 2.2 Deploy from source — no `cloudbuild.yaml`

**Recommendation: never write that file.** `gcloud run deploy --source` runs
Cloud Build, pushes to an auto-created **Artifact Registry** repo
(`cloud-run-source-deploy`, not legacy `gcr.io`), and deploys — in one command.
A `cloudbuild.yaml` here would exist only to restate what the Dockerfile and the
deploy flags already say, with no CI trigger calling it. That is exactly the
"layer that only forwards a call" CLAUDE.md says this repo keeps paying to
delete. Fix the stale docs by **deleting the claim**, not by writing the file.

```bash
gcloud run deploy book-rec-api \
  --source=backend/ --region=$REGION --no-allow-unauthenticated \
  --cpu=1 --memory=1Gi --cpu-boost --timeout=300 \
  --min-instances=0 --max-instances=3 --concurrency=5 \
  --set-env-vars="^@^APP_NAME=book-recommender-backend@APP_ENVIRONMENT=production@APP_ALLOW_ORIGINS=http://localhost:3000@POSTGRES_HOST=localhost@POSTGRES_PORT=5432@POSTGRES_DB=book_recommender@POSTGRES_USER=postgres@POSTGRES_PASSWORD=placeholder@POSTGRES_MIN_CONNECTIONS=2@POSTGRES_MAX_CONNECTIONS=12@OPENAI_API_KEY=placeholder@OPENAI_BASE_MODEL=gpt-4.1-mini@OPENAI_TOKENIZER_ENCODING=o200k_base@OPENAI_EMBEDDING_MODEL=text-embedding-3-large@OPENAI_EMBEDDING_DIMENSIONS=1024@OPENAI_MAX_CONCURRENCY=10"
```

- **`^@^` is load-bearing.** It changes gcloud's list delimiter from `,` to `@`.
  `APP_ALLOW_ORIGINS` will contain a comma in Stage 5; without this, gcloud
  splits it into two malformed env vars.
- Placeholders for the secrets are fine here — every `Settings` field is
  required with no default, so the process would fail at import without them.
  `config/constants.py:27` points `ENV_FILE` at a path absent from the image;
  pydantic-settings falls through to real env vars, which is the correct pattern.
  Stage 4 swaps these for Secret Manager references.
- No startup probe yet — it would fail with no database.

### ✅ Stage 2 checkpoint

```bash
URL=$(gcloud run services describe book-rec-api --region=$REGION --format='value(status.url)')
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $URL/ping
```
`{"status":"ok"}` means the image built, `$PORT` was honored and the app booted.
`/ready` returning 503 here is the correct answer — there is no database yet.

If `--source` fails on permissions (newer projects lack the legacy Cloud Build
SA), add `--build-service-account=...` with `roles/cloudbuild.builds.builder`
and `roles/artifactregistry.writer`.

---

# Stage 3 — Cloud SQL

### 3.1 Create the instance

```bash
# URL-safe alphabet on purpose — see the unescaped-interpolation note in Context.
PGPW=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)

gcloud sql instances create book-rec-db \
  --database-version=POSTGRES_16 --tier=db-g1-small --region=$REGION \
  --storage-size=10GB --storage-type=SSD --storage-auto-increase \
  --backup-start-time=08:00
gcloud sql users set-password postgres --instance=book-rec-db --password="$PGPW"
gcloud sql databases create book_recommender --instance=book-rec-db
```

POSTGRES_16 matches your local `pgvector/pgvector:pg16` and psql 16.14 — no
version skew. Public IP stays on with no authorized networks: the Auth Proxy
reaches it over IAM, Cloud Run over the `/cloudsql/` unix socket.

Install the proxy (not currently present):
one binary from the `GoogleCloudPlatform/cloud-sql-proxy` releases.

### 3.2 Dump books from the live container

`data/backup/` is empty, so regenerate from the running database — which is
cleaner than a stale file and gives exactly the books-only seed you chose.
Add this beside the existing `postgres-dump-*` family in `backend/Makefile`,
**without** `--column-inserts`: 1024-float vectors as individual INSERTs would
be enormous and slow, and plain `COPY` format is what you want.

```make
postgres-dump-books:   # pg_dump --table=books --data-only -> data/backup/books.sql
```

### 3.3 Bootstrap, in this order

There is no schema runner anywhere — `docker-compose.yml:29-31` mounts the SQL
into `/docker-entrypoint-initdb.d/`, which only fires on an empty data
directory. Add `cloudsql-proxy`, `cloudsql-bootstrap` and `cloudsql-cli` targets
so the proxy path is a first-class sibling of the `docker exec` ones.

1. **`00_extensions.sql`** — `vector` and `pg_trgm`. Cloud SQL PG16 allows both
   but nothing in the app creates them.
2. **`01_tables.sql`**
3. **Load `books.sql`**
4. **`02_indexes.sql` — last, deliberately.** `books_embedding_idx` is
   `ivfflat ... WITH (lists = 100)` (`02_indexes.sql:2-4`), and ivfflat builds
   its centroids from the rows present at creation time. Built on an empty table
   it is useless and similarity recall degrades *silently*. `books_search_idx`
   and `feedback_review_idx` also need their tables to exist.

**No migration runner needed.** I verified all seven files in
`db/schema/migrations/` are already folded into the base schema —
`writer JSONB` is in `01_tables.sql`, `books_search_idx` is in `02_indexes.sql`.
A fresh database gets the current schema from `00/01/02`. Building a runner now
is building for a caller that doesn't exist. The durable rule for the runbook: a
schema change lands in `db/schema/0*.sql` **and** a dated migration file, and
the migration is applied with `make cloudsql-cli ARGS="-f <file>"`.

### 3.4 Reconnect Cloud Run to the database

```bash
gcloud run services update book-rec-api --region=$REGION \
  --add-cloudsql-instances=$PROJECT:$REGION:book-rec-db \
  --update-env-vars="POSTGRES_HOST=/cloudsql/$PROJECT:$REGION:book-rec-db" \
  --startup-probe=httpGet.path=/ready,initialDelaySeconds=5,timeoutSeconds=5,periodSeconds=5,failureThreshold=6
```

`POSTGRES_HOST=/cloudsql/...` triggers the socket branch at
`config/settings/sqlalchemy.py:19-21` — already coded and unit-tested at
`tests/unit/config/test_settings.py:28-46`. No connector dependency.

**Use `/ready` as the startup probe.** Cloud Run's default check is TCP-on-$PORT,
and since `common/context.py:44-48` has `ping_services()` commented out, a
container with a wrong `POSTGRES_HOST` binds the port and goes live serving 500s
on every chat. `/ready` runs a real `SELECT 1`, so it catches exactly that: bad
socket path, wrong password, missing `--add-cloudsql-instances`. Zero code
change — `health.py:20-46` already returns 503 on failure, and a failing probe
means the revision never goes live and the previous one keeps serving.

Do **not** re-enable `ping_services()` instead: it also calls
`OpenAIClient.ping()`, a **billed API call on every cold start**, and couples
boot to a third party. Nothing else calls it — delete it with the dead comment.

No liveness probe: a transient DB blip would kill healthy containers mid-stream.

### Pool sizing

The binding constraint is easy to miss. `get_sqlalchemy_session`
(`app/api/dependencies.py:42-53`) is a **`yield` dependency**, so its connection
is held for the *entire SSE stream*, not per query — and once Stage 4 uncomments
the recorder, `record_chat_run` opens a **second, independent** session while
the first is still open. So peak is **2 connections per in-flight turn**.

| Knob | Value | Why |
|---|---|---|
| `--concurrency` | 5 | 5 turns × 2 conns = 10 |
| `--max-instances` | 3 | ~15 concurrent turns; under the 500 RPM tier in `docs/backlog.md:52-58` |
| `POSTGRES_MIN_CONNECTIONS` | 2 | `pool_size` |
| `POSTGRES_MAX_CONNECTIONS` | 12 | pool 2 + overflow 10 (`db/async_engine.py:32-34`) |
| Worst case | 36 | 3 × 12, inside `db-g1-small`'s ~50 |

The shipped defaults (`.env.example:18-19`, MIN=5/MAX=20) are **per instance** —
at 3 instances that is 60 and blows the cap. Both are env-driven, so this is
config, not code. Confirm with
`make cloudsql-cli ARGS='-c "SHOW max_connections;"'`.

### ✅ Stage 3 checkpoint

Through the proxy: `\dx` lists `vector` + `pg_trgm`; `SELECT count(*) FROM
books` → **5197**; `\di` shows four indexes. Then
`curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $URL/ready`
→ **200**. That 200 is the real proof the socket path works.

---

# Stage 4 — Security, and turn recording back on

Everything here is code, verified with `make tests-all` before redeploying.

### 4.1 Admin gate on the review surface

`GET /chat_runs` (`app/api/routes/chat_run.py:9-20`) returns every session's
`user_message`, the writer envelope and full planner/task JSONB traces,
unscoped and unauthenticated. The feedback routes take a caller-supplied
`chat_id`/`session_id` and upsert whatever is passed.

On the backlog's "real session-ownership verification, not 'the ID is hard to
guess'" (`docs/backlog.md:21-25`): that **cannot be satisfied as written**.
`POST /session/new` hands out session ids to anyone with no credential, so there
is no identity to verify against. `db/schema/01_tables.sql` already calls
`feedback` "Reviews from the internal /review page" — this plan takes it at its
word and gates the surface, which closes the disclosure *and* the tampering
item together and dissolves the ownership question: the session id stops being
the credential, so guessing it buys nothing.

- `config/settings/app.py` — add `ADMIN_TOKEN: str` (picks up `APP_ADMIN_TOKEN`
  from the existing `env_prefix="APP_"`).
- `app/api/dependencies.py` — one `require_admin(x_admin_token: str = Header(...))`
  raising 403, using **`secrets.compare_digest`**, not `==`, which
  short-circuits on the first differing byte.
- `app/main.py` — apply router-level, not per-route, so routes added later are
  covered by default:
  `app.include_router(chat_run_router, dependencies=[Depends(require_admin)])`.
- Add `APP_ADMIN_TOKEN=` to `config/.env.example` **and** to
  `.github/workflows/ci.yml`'s env block — every `Settings` field is required
  with no default, so CI breaks otherwise.

**Be honest about the limit:** a `VITE_*` value is baked into the Vite bundle in
plaintext. So **do not ship `/review` publicly.** Keep the token in your *local*
`frontend/.env` and run the review page locally; the Firebase bundle ships
without it, serving `/` and `/blog`. A genuinely public review page needs real
auth (Firebase Auth) and is separate work — don't fake it with a bundled token.

### 4.2 Turn recording

Uncomment `app/orchestration/run_recorder.py:186-188`. Without it the deployed
app records nothing at all, and `/chat_runs` stays permanently empty.

Sequencing note: because prod starts with an empty `chat_runs` and the recorder
is off, **today's disclosure risk is prospective, not retroactive.** It becomes
real the moment you uncomment these lines — which is why they belong in the same
stage as the gate, not before it.

### 4.3 CORS

`app/main.py:53-59` sets `allow_credentials=True`, so `*` is not merely sloppy —
browsers reject it outright. Set exact origins in Stage 5. Tighten
`allow_methods=["*"]` → `["GET","POST","PUT","OPTIONS"]`, clearing the TODO at
line 57, and narrow `allow_headers` to `["Content-Type","X-Admin-Token"]`.

Drop `ngrok-skip-browser-warning` from `frontend/src/api.js:33` in the same
change — ngrok is gone after this, and leaving it forces it back into the
allow-list.

### 4.4 Message length bounds

`app/api/schemas/external.py` — the backlog names `FeedbackIn.message`; the real
class is `ReviewCommentIn` (line 14). Add `max_length`. Move the `2000` literal
out of `app/api/routes/chat_message.py:70-74` onto `ChatIn.message` as a `Field`
constraint, with the bound in `config/constants.py` per CLAUDE.md's "no literals
at the call site"; the whitespace check at line 66 becomes `min_length=1` plus a
strip validator.

### 4.5 Secrets and a real service account

```bash
SA=book-rec-api@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create book-rec-api --display-name="Book Recommender API"
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA \
  --role=roles/cloudsql.client

# printf '%s', never echo: a trailing newline breaks auth in a way that looks
# exactly like a wrong credential.
printf '%s' "$PGPW"           | gcloud secrets create postgres-password --data-file=-
printf '%s' "$OPENAI_API_KEY" | gcloud secrets create openai-api-key   --data-file=-
printf '%s' "$ADMIN_TOKEN"    | gcloud secrets create admin-token      --data-file=-
for s in postgres-password openai-api-key admin-token; do
  gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$SA \
    --role=roles/secretmanager.secretAccessor
done
```

A dedicated SA, not the compute default —
`286869228046-compute@developer.gserviceaccount.com` carries project Editor, so
a compromised container would have project-wide write.

Then redeploy with `--service-account=$SA` and
`--set-secrets=OPENAI_API_KEY=openai-api-key:latest,POSTGRES_PASSWORD=postgres-password:latest,APP_ADMIN_TOKEN=admin-token:latest`,
dropping the placeholder env vars.

### 4.6 Wrap it in `make deploy`

Put the full command in a `deploy` target in `backend/Makefile` — the repo's
existing idiom (cf. `frontend/Makefile:34`) — so the recipe is the whole
description of the service and nothing lives only in the console. GitHub Actions
CD comes later; `.github/workflows/ci.yml` already has the env matrix it needs.

### What I'd leave open

**`uuid_8()`'s 32 bits** (`airglider/src/utils.py:24`). ~1% collision odds at
~9,300 rows, 50% at ~77k. A collision is a PK conflict on the `chat_runs`
insert — the user still gets their answer, you lose one record. That is a
data-quality bug, not a security one, and it is a one-line change in airglider
whenever you next touch it. Leave it on the roadmap with this reasoning rather
than doing it under a deploy deadline.

**The real financial exposure is not on that list.** There is no rate limit on
`POST /session/{id}/message`, and each turn is ~15 OpenAI calls. The zero-code
answer you chose: a **hard monthly spend cap on the OpenAI account** (2 minutes,
account-level) plus a GCP billing alert, with `--concurrency=5 ×
--max-instances=3` as the crude throughput ceiling. Do the spend cap before
Stage 5, not after.

### ✅ Stage 4 checkpoint

`make tests-all`. Then against the still-private service: `/chat_runs` → 403
without `X-Admin-Token`, rows with it. Send a chat turn and confirm a row lands
in `chat_runs` via `make cloudsql-cli`.

---

# Stage 5 — Go public

### 5.1 Open the service and set real origins

```bash
gcloud run services update book-rec-api --region=$REGION \
  --update-env-vars="^@^APP_ALLOW_ORIGINS=https://tuanqpham0921.web.app,https://tuanqpham0921.firebaseapp.com"
gcloud run services add-iam-policy-binding book-rec-api --region=$REGION \
  --member=allUsers --role=roles/run.invoker
```

Firebase serves both hostnames, so both must be listed.

### 5.2 Point the frontend at it

`frontend/Makefile` already has everything: `deploy-tunnel URL=` is literally
`set-api-url` + `deploy` chained, and is already URL-agnostic — only the name
says "tunnel". Two small edits, no new machinery:

1. **Rename `deploy-tunnel` → `deploy-url`** (it is no longer tunnel-specific),
   updating the referring comment at `backend/Makefile:28-30`.
2. **Add a 4-line `deploy-prod`** pinning the Cloud Run URL. The footgun is
   real: `.env` says `http://localhost:8000`, and a plain `make deploy` ships
   whatever is there — one `make dev` session and you have published a localhost
   bundle.

Then delete the commented-out `BASE_URL` at `frontend/src/api.js:2`; it is the
thing that drifts.

### 5.3 Consider min-instances=1

You chose cold starts, which is right for now. But before you *share* the link,
`gcloud run services update book-rec-api --min-instances=1` costs roughly
$7/month — noise next to the Cloud SQL instance — and removes the 5-8s
first-chat penalty that is most visible on exactly this low-traffic demo
pattern. `--cpu-boost` shortens whatever cold start remains.

### ✅ Stage 5 checkpoint

Load `tuanqpham0921.web.app`, send a message, confirm SSE streams and cards
render. Check the console for CORS errors — that is where a mis-escaped
`APP_ALLOW_ORIGINS` surfaces.

---

# Stage 6 — Docs

Required by CLAUDE.md's "keep docs in sync" rule, and overdue: both current
deployment claims are false.

- **`README.md:52-56`** — replace the `gcloud builds submit --config
  cloudbuild.yaml` line with `cd backend && make deploy`. Also line 18,
  "Python 3.11+" → 3.12+.
- **`CLAUDE.md` Infrastructure section** — name the service `book-rec-api`, the
  Artifact Registry repo `cloud-run-source-deploy`, the instance
  `tuanqpham0921:us-central1:book-rec-db`, and the `/cloudsql/` socket path.
- **New `docs/deploy.md`** — the runbook: one-time setup, the Stage 3 bootstrap
  ordering *with why indexes come last*, the env/secret table, how to re-seed.
  Operations rather than a decision record, so `docs/` root, not `docs/design/`.
  **Add a row to `docs/README.md`'s doc-map table** — that table is the
  convention, and a file missing from it is invisible.
- **`docs/roadmap.md:180-187`** — tick the items Stage 4 closes; leave `uuid_8`
  open with the reasoning above, and record that the ownership item was closed
  by admin-gating.
- **`docs/backlog.md`** — strike the closed P1 items; add two P2s: the unescaped
  interpolation at `config/settings/sqlalchemy.py:21` (with the two-line
  `quote_plus` fix written down, so whoever rotates the password later doesn't
  lose a day), and the `lists=100` recall question below.
- **`frontend/src/README.md:11`** already flags `stopChatStream`,
  `getTaskPlanDiagram` and `getRecommendedBooks` as dead — I confirmed they call
  routes that do not exist. Not a blocker; worth deleting while you are in
  `api.js` anyway for 4.3.

---

## Deferred, with reasons

- **`lists = 100` is wrong for 5,197 rows.** pgvector's guidance is
  `rows/1000` ≈ 5. At 100, each list holds ~52 rows and the default
  `ivfflat.probes = 1` scans one — recalling ~1% of the table per query. At this
  size an exact scan is single-digit milliseconds anyway. **Keep 100 for parity
  with local** (changing it changes eval results) and log it as a recall
  question, not a deploy action.
- **`quote_plus` on the DB URL** — generating a URL-safe password is a smaller
  change that costs zero code. Write the landmine down; don't build around it
  now.
- **pandas is never imported at runtime** (verified by grep across `app/
  common/ db/ clients/ config/ airglider/`). It pulls ~100MB with numpy for
  evals and notebooks only. Moving it to the dev group is correct but churns
  `poetry.lock` — do it after the image is proven, not during.

## Risks

- **`db-g1-small` is shared-core.** If similarity queries feel slow, the tier
  changes without a rebuild.
- **The books seed depends on your local container staying populated** — it is
  now the only copy with embeddings, since `data/backup/` is empty. Consider
  running `postgres-dump-books` and keeping the artifact somewhere safe before
  Stage 3, independent of the deploy.
- **Re-embedding is not a cheap fallback.** If the local data were lost,
  regenerating 5,197 embeddings costs real OpenAI spend; `data/books.csv` has no
  vectors.
