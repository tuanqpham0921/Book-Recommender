# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Map & Conventions

- **`docs/`** is the durable planning layer: [roadmap](docs/roadmap.md), [backlog](docs/backlog.md), [eval strategy](docs/eval-strategy.md), and design decision records (`docs/design/`). The `TODO.md` files in `backend/`/`frontend/` are ephemeral scratchpads only. Eval campaign outputs stay in `backend/evals/results/`.
- **Read the nearest folder's `README.md` before making changes there** — most backend/frontend folders have one with the local context (e.g. `backend/app/`, `backend/app/domains/`, `backend/db/`, `backend/evals/`, `frontend/src/`).
- **Keep docs in sync**: a change to routes, the node registry, enums, or the request flow must update the nearest README, this file's architecture section, and the relevant `docs/` file in the same change.

## Files to Avoid Reading

To save tokens, do not read these unless the task specifically requires it:

- **Log files** (`backend/logs/` — `*.log` and chat-run JSON dumps): skip unless the task is formatting or restructuring the logs themselves.
- **SQL backups/dumps** (`backend/data/*.sql`, e.g. `backup.sql`; `backend/evals/results/**/*.sql` raw eval dumps): never read these. The schema init SQL in `backend/db/schema/` (extensions/tables/indexes) is fine to read.
- **`backend/playground/app_mock/`** — **outdated, ignore.** The mock executors and extended node schemas were the stand-in used for eval testing before the slices had real executors. They are no longer maintained and nothing live reads them (`EXECUTORS_CLS_MAPPING` points at the real slice executors). Don't read them for context, don't update them alongside a change to the real code, and don't model new code on them.

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
make tools-catalog              # inventory the planner's tool catalog (no backend/DB needed)
```

Evals live in `backend/evals/`: suite definitions in `evals/suites/*.json` (versioned inputs), the runner `evals/run_suites.py` (after a run it writes one `test_runs` row per query — chat_id FK to `chat_runs` plus the suite file stem and entry id), make targets in `evals/makefile`, and per-campaign reports/raw dumps in `evals/results/`.

Two post-processors split correctness from spend, over shared plumbing in `evals/common.py` (the `test_runs ⋈ chat_runs` fetch, latest-per-case filtering, suite-JSON lookup, CLI):

- **`evals/report_system_goals.py`** (`make suite-goals`) — diffs accepted goal types against each case's `expected_nodes`, saves to `evals/results/system_goals_<timestamp>.md`. **This diff is the project's golden-test mechanism**; it deliberately reports no token/cost/latency numbers.
- **`evals/report.py`** (`make suite-stats`) — ok/failed, runtime errors, duration, tokens, cache hit rate, dollars, and a per-model spend split.

`make suite-reports` runs both. A third report, **`evals/tools_catalog.py`** (`make tools-catalog`), stands apart from those two: it reads the **live registry instead of the database**, so it needs no backend and no recorded run. It inventories the planner's tool catalog — tool count per tier, per-tool token cost and share, the per-request cost of shipping the catalog (uncached and cached), plus an audit for nodes with no executor and docstrings missing a canonical section. Run it after adding or editing a node. Strategy and growth plan in [docs/eval-strategy.md](docs/eval-strategy.md).

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

Each capability is a **vertical slice** — one folder under `app/domains/<domain>/<node>/` holding its label, request/output schemas and executor, exporting a single `NodeSpec` (`app/domains/node_spec.py`). A domain's `guide.py` lists its specs; `app/registry.py` composes those into `SPECS` and **derives** everything else: `NODE_TYPE_TO_CLS`, the catalog tiers, `AnyStrategyRequest`, the flat `NodeTypeEnum` the planner emits, and the executor mapping. Nothing there is hand-maintained per node. Schemas describe *what* to do; **executors** (the *how*) subclass `NodeBaseWorkflow` and are reached through the spec — `EXECUTORS_CLS_MAPPING` is the real `NODE_EXECUTORS_CLS_MAPPING`, derived from the slices. The "PLAYGROUND EXTENSION" block at the bottom of `registry.py` folds ~18 scaling-test node types into the live registry; it is a deliberate **manual comment-toggle** (currently *disabled* on `minimal_end_to_end_v1`, as of 2026-08-04 — 2 registered node types). To see what the planner is actually told it can do at any moment, run `make tools-catalog` rather than trusting a checked-in snapshot: it renders the live registry, so it reflects the toggle's current state.

**Adding a new capability:** see the step-by-step recipe in `backend/app/domains/README.md` (new slice folder → request schema with LLM-facing docstring → `SPEC` → one line in the domain's `guide.py` → eval cases). The planner picks it up automatically via the tool-loading step. The V1 node set is a settled decision: [docs/design/node-taxonomy-v1.md](docs/design/node-taxonomy-v1.md).

### Request Flow

1. **Frontend** sends a chat message via SSE to `POST /session/{id}/message`
2. **`Orchestrator`** (`app/orchestration/orchestrator.py`) builds a `RequestContext` and delegates to `PlannerWorkflow`
3. **`PlannerWorkflow`** runs the planner pipeline (parse → classify → diagram)
4. Results stream back to the client via **SSEStream** (`app/common/sse_stream.py`)

**Current state:** `TaskRunnerWorkflow` (`app/domains/task_runner.py`) executes the classified strategies against the real executors, for the node types registered on this branch. It brackets each node with `task.start`/`task.end` SSE events so the UI can render one collapsible section per step (count in the header, preview cards inside); see `frontend/src/README.md`. Conversation is **single-turn**: each request is processed statelessly (turns are recorded to `chat_runs` but never read back).

### API Surface

`GET /health` · `GET /ping` · `GET /ready` — health/readiness. `POST /session/new` — mints a session id. `POST /session/{session_id}/message` — SSE chat. `GET /chat_runs` — review queue (least-reviewed first). `PUT /feedback/review` — upsert one review per (chat_id, session_id). `GET /feedback?chat_id=` — list reviews for a run. That is the whole surface — there is no `/add_feedback` and no `/chat_runs/tests`. No auth exists yet (pre-deploy blocker, docs/backlog.md).

### Workflow / Operation Pattern

Infrastructure abstractions in `common/` that centralize logging, error catching, and structured output — so production code never crashes silently and every result carries consistent metadata.

- **`OperationResult[T]`** (`common/operation.py`) — universal result envelope: `ok`, `message`, `output`, `steps`, `run_time_error`, `duration`, `id`. All steps and workflows return this. Parent callers access child output via `.output`.
- **`Workflow`** (`common/workflow.py`) — for multi-step async processes. Subclass and override `run()`. Centralizes start/error logging and catches runtime exceptions without crashing. Each `Workflow` owns one `OperationResult` in memory; steps append to `.steps` as they complete. `UserFacingBaseWorkflow` adds SSE streaming helpers.
- **`@task` decorator** (`common/operation.py`) — for single async functions. Wraps the function, catches exceptions, and returns `OperationResult`. To add detail or custom messages from inside a `@task`, return a custom `OperationResult` directly — the decorator detects this and passes it through unchanged.

### Domain / Node Type System

`app/domains/` defines what the system can do:

- **The book node set.** The V1 taxonomy is `Retrieve_by_ISBN13`, `Retrieve_by_Title`, `Retrieve_by_Author`, `Retrieve_by_CoAuthors`, `Retrieve_by_Genre`, `Retrieve_Random`, `Combine_Union`, `Combine_Intersect`, `Filter_Retrieval`, `Analyze_Compare`, `Analyze_Recommend`. **On `minimal_end_to_end_v1` only `Retrieve_by_Title` and `Analyze_Recommend` are registered** — the rest are parked while the end-to-end path is built, so the rules below describe the target taxonomy, not what the planner can currently emit. `make tools-catalog` prints what is actually live. Each retrieval node is single-dimension (no cross-column filtering) and single-valued — one title, one author, one genre per node; several authors' separate bibliographies means several `Retrieve_by_Author` nodes. `Retrieve_by_CoAuthors` is the one multi-value node and means joint works only (2+ authors ANDed onto the same book), not a combined bibliography — see [docs/design/node-taxonomy-v1.md](docs/design/node-taxonomy-v1.md). `Retrieve_Random` is the one node that carries a full `BooksFilter` (a random pick has no dimension to be single about); it serves the bare "recommend me a book" **alone**, with no `Analyze_Recommend` after it, and `Filter_Retrieval` may never depend on it — bounds on a surprise go in its own `filters`. Cross-dimension requests are expressed by composition instead: the **combine tier** (`Combine_Union` = OR, `Combine_Intersect` = AND, `Filter_Retrieval` = metadata narrowing) consumes prior retrieval output and never queries the database. Pooling is also implicit — several task ids in one `depends_on` are pooled (OR) by definition — so `Combine_Union` is only used when that pooled set is an explicit step something downstream consumes — see [docs/design/execution-pipeline-v1.md](docs/design/execution-pipeline-v1.md). This domain's specs are listed in `app/domains/books/guide.py`; `app/registry.py` composes it with the other domains.
- **`NodeTypeEnum`** — the flat enum of every registered capability name plus `unknown`, built from `SPECS` in `app/registry.py`. It is what `SystemGoal.target_node_type` is typed as, so it is the constraint the planner LLM emits under. `unknown` is a member on purpose: it lets the model decline rather than pick a wrong capability, and `parse_intent.py` refuses that goal with a reason instead of failing the whole tool call.
- **Shared output shapes** — `app/domains/books/schemas.py` (`Book`, `BookRetrievalOutput`, `BookRecommendationOutput`). A node's own output subclasses the shape its docstring claims in `Returns:`. `Book` is the single book model — every `books` column except `embedding` — and stays that way on purpose: narrow at the point of use (a prompt renderer picking fields, `model_dump(include=...)`), never by declaring a smaller model.
- **Domain base workflow** — `app/domains/books/base_workflow.py` (`BookBaseWorkflow`), one layer under the domain-agnostic `NodeBaseWorkflow` (`app/domains/base_workflow.py`).
- **Naming (`Base` / `Workflow` / `Executor`)** — **`Base` marks a reusable base class**, not `Workflow`: the ladder is `Workflow` → `AppBaseWorkflow` → `NodeBaseWorkflow` → `BookBaseWorkflow`, all in `workflow.py`/`base_workflow.py` files. Concrete units of work are `*Workflow` too (`PlannerWorkflow`, `InitialParseWorkflow`, `TaskRunnerWorkflow`). **`Executor` is the subset of those the planner can dispatch** — a node with a request schema, a `NodeSpec` and a catalog entry, reached via `EXECUTORS_CLS_MAPPING` instead of called directly. Node vs. pipeline step is what the second word carries; it is not a concrete-vs-reusable distinction. See `backend/app/domains/README.md`. Book slices subclass it and implement **`execute(query, dependent_results)`** rather than `run()`: `run()` binds `self.store` from the request context first. It also carries `preflight(query)` — stamps `query`/`query_sql`/`num_books` on the output and returns `(total, sample)` from one `BookStore.preview` round trip, leaving `output.books` to the caller — and `stream_books()`, which validates through `BookOut` before anything reaches the browser.
- `app/registry.py` derives every node lookup from `SPECS`

### Database

- **PostgreSQL + pgvector** via async SQLAlchemy (`db/async_engine.py`)
- Schema SQL in `db/schema/` (extensions → tables → indexes)
- SQLAlchemy models in `db/schema/models.py`
- Repository pattern in `db/stores/` — `book_store.py` is the primary store. Retrieval is **counts-first**: `title_query()` builds a `DeferredBookQuery` that isn't run for rows, `count()` runs only a `COUNT`, `compose()` folds several into one CTE, and `materialize()` is the single place rows are fetched — at the end of a plan. See `db/README.md` and [docs/design/execution-pipeline-v1.md](docs/design/execution-pipeline-v1.md)
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
