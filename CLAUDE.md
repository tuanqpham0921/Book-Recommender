# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (run from `backend/`)

```bash
poetry install                  # install dependencies
make dev                        # start FastAPI with hot reload on :8000
make tests                      # run unit + integration tests
poetry run pytest -s tests/unit/path/to/test_file.py  # run a single test
make ingestion                  # run the book data ingestion script
make postgres-start             # start PostgreSQL via Docker Compose
make postgres-stop              # stop PostgreSQL container
make postgres-restore           # restore data from data/backup.sql
make postgres-cli               # open psql shell
```

Environment config lives at `config/.env` (see `config/README` for structure).

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

### Planner Pipeline (`app/orchestration/planner/`)

1. **`parse_intent.py` (`InitialParseWorkflow`)** — sends the user message to the LLM with all available tool schemas (descriptions come from docstrings on the node classes). Returns a list of goals with IDs.
2. **`strategy_classification.py` (`StrategyClassificationWorkflow`)** — takes those goals, loads the matching tools, and has the LLM select strategies via semantic understanding. The LLM can reject goals and resolves dependencies to produce an ordered execution plan.
3. **`ConversationOrchestrator`** (`planner/main.py`) — receives the plan, generates the Mermaid diagram, streams it to the frontend, then instantiates the node classes and runs them with the parsed arguments.

Node implementations live in `app/domains/` keyed by `NodeTypeEnum`. `app/domains/registry.py` maps type strings to classes.

**Adding a new capability:** add a node class under the appropriate domain, register it in `registry.py`, and define its `BookNodeTypeEnum` entry — the planner picks it up automatically via the tool-loading step.

### Request Flow

1. **Frontend** sends a chat message via SSE to `POST /session/{id}/message`
2. **`Orchestrator`** (`app/orchestration/orchestrator.py`) builds a `RequestContext` and delegates to `ConversationOrchestrator`
3. **`ConversationOrchestrator`** runs the planner pipeline (parse → classify → diagram → execute)
4. Results stream back to the client via **SSEStream** (`app/common/sse_stream.py`)

### Workflow / Operation Pattern

Infrastructure abstractions in `common/` that centralize logging, error catching, and structured output — so production code never crashes silently and every result carries consistent metadata.

- **`OperationResult[T]`** (`common/operation.py`) — universal result envelope: `ok`, `message`, `output`, `steps`, `run_time_error`, `duration`, `id`. All steps and workflows return this. Parent callers access child output via `.output`.
- **`Workflow`** (`common/workflow.py`) — for multi-step async processes. Subclass and override `run()`. Centralizes start/error logging and catches runtime exceptions without crashing. Each `Workflow` owns one `OperationResult` in memory; steps append to `.steps` as they complete. `UserFacingBaseWorkflow` adds SSE streaming helpers.
- **`@task` decorator** (`common/operation.py`) — for single async functions. Wraps the function, catches exceptions, and returns `OperationResult`. To add detail or custom messages from inside a `@task`, return a custom `OperationResult` directly — the decorator detects this and passes it through unchanged.

### Domain / Node Type System

`app/domains/` defines what the system can do:

- **`BookNodeTypeEnum`** — `Retrieve_by_ISBN13`, `Retrieve_by_Title`, `Retrieve_by_Traits`, `Analyze_Compare`, `Analyze_Recommend`
- **`NodeTypeEnum`** — union of Book/User/Project/Unknown node types
- `app/domains/registry.py` maps node type strings to their implementations

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

- Single-page React app — one route `/` and `/blog` both render `BookRecommenderPage`
- `src/api.js` — all backend calls; uses `VITE_API_URL`; SSE streaming handled in the chat component
- State management uses `use-immer` for complex nested state
- Mermaid diagrams rendered client-side with pan/zoom via `@panzoom/panzoom`
- Blog posts are static markdown files in `public/blog-posts/`

### Infrastructure

- **Backend**: Google Cloud Run, deployed via `gcloud builds submit`
- **Frontend**: Firebase Hosting
- **Database**: Cloud SQL (PostgreSQL)
- Local dev uses Docker Compose for PostgreSQL only (see `backend/docker-compose.yml`)
