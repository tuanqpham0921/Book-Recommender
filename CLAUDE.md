# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Map & Conventions

- **`docs/`** is the durable planning layer: [roadmap](docs/roadmap.md), [backlog](docs/backlog.md), [eval strategy](docs/eval-strategy.md), and design decision records (`docs/design/`). The `TODO.md` files in `backend/`/`frontend/` are ephemeral scratchpads only. Eval campaign outputs stay in `backend/evals/results/`.
- **Read the nearest folder's `README.md` before making changes there** — most backend/frontend folders have one with the local context (e.g. `backend/app/`, `backend/app/domains/`, `backend/db/`, `backend/evals/`, `backend/playground/`, `frontend/src/`).
- **Keep docs in sync**: a change to routes, the node registry, enums, or the request flow must update the nearest README, this file's architecture section, and the relevant `docs/` file in the same change.

## Files to Avoid Reading

To save tokens, do not read these unless the task specifically requires it:

- **Log files** (`backend/logs/` — `*.log` and chat-run JSON dumps): skip unless the task is formatting or restructuring the logs themselves.
- **SQL backups/dumps** (`backend/data/*.sql`, e.g. `backup.sql`; `backend/evals/results/**/*.sql` raw eval dumps): never read these. The schema init SQL in `backend/db/schema/` (extensions/tables/indexes) is fine to read.

If a file is in gitignore, you probably don't need to read it.
Ask for confirmation before reading large files

## Commands

### Backend (run from `backend/`)

```bash
poetry install                  # install dependencies
make dev                        # start FastAPI with hot reload on :8000
make tests                      # run unit tests (tests/unit/)
make tests-integration          # in-process API tests (tests/integration/) — faked stores, no services needed
make tests-all                  # both of the above
poetry run pytest -s tests/unit/path/to/test_file.py  # run a single test
make ingestion                  # run the book data ingestion script
make postgres-start             # start PostgreSQL via Docker Compose
make postgres-stop              # stop PostgreSQL container
make postgres-restore           # restore data from data/backup.sql
make postgres-cli               # open psql shell
make query-suite                # POST the base eval suite at a running backend (make dev first)
make query-suite-all            # fire all 4 eval suites concurrently
```

Evals live in `backend/evals/`: suite definitions in `evals/suites/*.json` (versioned inputs), the runner `evals/run_suites.py` (after a run it writes one `test_runs` row per query — chat_id FK to `chat_runs` plus the suite file stem and entry id), the post-processor `evals/eval.py` (`make suite-eval` — joins `test_runs ⋈ chat_runs`, diffs accepted goal types against each case's `expected_nodes`, saves a report to `evals/results/`), make targets in `evals/makefile`, and per-campaign reports/raw dumps in `evals/results/`. **This suite/expected_nodes diff is the project's golden-test mechanism** — strategy and growth plan in [docs/eval-strategy.md](docs/eval-strategy.md).

Environment config lives at `config/.env` (see `config/README.md` for structure).

### Frontend (run from `frontend/`)

```bash
npm install     # install dependencies
npm run dev     # start Vite dev server
npm run build   # production build
npm run lint    # run ESLint
```

Frontend reads `VITE_API_URL` from `.env` to locate the backend.

---

## Architecture

### Design: Request-Based Planning (not a static graph)

Instead of a fixed routing graph, this system uses **LLM-driven preplanning**: the user's message is turned into structured schema requests that an LLM fills out, producing an explicit task plan before any retrieval or analysis runs.

**Why:** New capabilities only require adding a tool schema — no graph rewiring. The preplanning step also produces a Mermaid diagram the user sees before execution, which aids debugging and builds trust.

**Tradeoff:** Two LLM calls (parse + classify) before real work starts. Acceptable for a chatbot where latency expectations are relaxed.

### Planner Pipeline (`app/domains/planner/`)

1. **`parse_intent.py` (`InitialParseWorkflow`)** — sends the user message to the LLM with all available tool schemas (descriptions come from docstrings on the node request-schema classes). Returns a list of goals with IDs.
2. **`strategy_classification.py` (`StrategyClassificationWorkflow`)** — takes those goals, loads the matching tools, and has the LLM select strategies via semantic understanding. The LLM can reject goals and resolves dependencies to produce an ordered execution plan (topological sort, cycle rejection).
3. **`PlannerWorkflow`** (`planner/main.py`) — receives the plan, generates the Mermaid diagram, and streams it plus the goal list to the frontend. (Task execution happens in `TaskRunnerWorkflow`, currently disabled — see Request Flow below.)

Node **request schemas** live in `app/domains/` keyed by `NodeTypeEnum`; `app/registry.py` maps type strings to classes. Schemas describe *what* to do; **executors** (the *how*) are looked up separately via `EXECUTORS_CLS_MAPPING` in the same file — currently pointing at the **mock executors** in `playground/app_mock/` until real ones are built. The "PLAYGROUND EXTENSION" block at the bottom of `registry.py` folds ~18 scaling-test node types into the live registry; it is a deliberate **manual comment-toggle** (currently enabled) — see `backend/playground/README.md`.

**Adding a new capability:** see the step-by-step recipe in `backend/app/domains/README.md` (enum entry → request schema with LLM-facing docstring → registry → executor mapping → eval cases). The planner picks it up automatically via the tool-loading step. The V1 node set is a settled decision: [docs/design/node-taxonomy-v1.md](docs/design/node-taxonomy-v1.md).

### Request Flow

1. **Frontend** sends a chat message via SSE to `POST /session/{id}/message`
2. **`Orchestrator`** (`app/orchestration/orchestrator.py`) builds a `RequestContext` and delegates to `PlannerWorkflow`
3. **`PlannerWorkflow`** runs the planner pipeline (parse → classify → diagram)
4. Results stream back to the client via **SSEStream** (`app/common/sse_stream.py`)

**Current state:** `TaskRunnerWorkflow` (`app/domains/task_runner.py`) — the step that would actually execute the classified strategies — is implemented but currently commented out in `Orchestrator.run`. Today's request flow only runs the planner pipeline through diagram generation; it does not yet execute tasks end-to-end. Conversation is **single-turn**: each request is processed statelessly (turns are recorded to `chat_runs` but never read back).

### API Surface

`GET /health` · `GET /ping` · `GET /ready` — health/readiness. `POST /session/new` — mints a session id. `POST /session/{session_id}/message` — SSE chat. `GET /chat_runs` — review queue (least-reviewed first). `PUT /feedback/review` — upsert one review per (chat_id, session_id). `GET /feedback?chat_id=` — list reviews for a run. That is the whole surface — there is no `/add_feedback` and no `/chat_runs/tests`. No auth exists yet (pre-deploy blocker, docs/backlog.md).

### Workflow / Operation Pattern

Infrastructure abstractions in `common/` that centralize logging, error catching, and structured output — so production code never crashes silently and every result carries consistent metadata.

- **`OperationResult[T]`** (`common/operation.py`) — universal result envelope: `ok`, `message`, `output`, `steps`, `run_time_error`, `duration`, `id`. All steps and workflows return this. Parent callers access child output via `.output`.
- **`Workflow`** (`common/workflow.py`) — for multi-step async processes. Subclass and override `run()`. Centralizes start/error logging and catches runtime exceptions without crashing. Each `Workflow` owns one `OperationResult` in memory; steps append to `.steps` as they complete. `UserFacingBaseWorkflow` adds SSE streaming helpers.
- **`@task` decorator** (`common/operation.py`) — for single async functions. Wraps the function, catches exceptions, and returns `OperationResult`. To add detail or custom messages from inside a `@task`, return a custom `OperationResult` directly — the decorator detects this and passes it through unchanged.

### Domain / Node Type System

`app/domains/` defines what the system can do:

- **`BookNodeTypeEnum`** — `Retrieve_by_ISBN13`, `Retrieve_by_Title`, `Retrieve_by_Traits`, `Analyze_Compare`, `Analyze_Recommend`
- **`NodeTypeEnum`** — union of Book/User/Project/Unknown node types
- `app/registry.py` maps node type strings to their implementations

### Database

- **PostgreSQL + pgvector** via async SQLAlchemy (`db/async_engine.py`)
- Schema SQL in `db/schema/` (extensions → tables → indexes)
- SQLAlchemy models in `db/schema/models.py`
- Repository pattern in `db/stores/` — `book_store.py` is the primary store
- `db/ingestion/` populates books from `data/books.csv` — **legacy, ignore**: still uses old `Workflow`/`@task` patterns and will be reworked later; don't refactor it or model new code on it

### Config

- **`Settings`** (`config/settings/main.py`) — pydantic-settings, loaded from `config/.env`; has `app`, `openai`, `sqlalchemy` sub-settings
- **`FilesLocationConstants`** / **`AppConfig`** etc. — path and domain constants from `config/constants.py`
- Import via `from config import settings, FilesLocationConstants`

### Frontend

- Single-page React app — `/`, `/blog`, and `/review` all render `BookRecommenderPage`, which maps the path to a view (chat / blog post / review queue); see `frontend/src/README.md`
- `src/api.js` — all backend calls; uses `VITE_API_URL`; SSE streaming handled in the chat component
- State management uses `use-immer` for complex nested state
- Mermaid diagrams rendered client-side with pan/zoom via `@panzoom/panzoom`
- Blog posts are static markdown files in `public/blog-posts/`

### Infrastructure

- **Backend**: Google Cloud Run, deployed via `gcloud builds submit`
- **Frontend**: Firebase Hosting
- **Database**: Cloud SQL (PostgreSQL)
- Local dev uses Docker Compose for PostgreSQL only (see `backend/docker-compose.yml`)
