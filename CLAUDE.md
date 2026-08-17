# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Map & Conventions

- **`docs/`** is the durable planning layer: [roadmap](docs/roadmap.md), [backlog](docs/backlog.md), [eval strategy](docs/eval-strategy.md), and design decision records (`docs/design/`). The `TODO.md` files in `backend/`/`frontend/` are ephemeral scratchpads only. Eval campaign outputs stay in `backend/evals/results/`.
- **Read the nearest folder's `README.md` before making changes there** — most backend/frontend folders have one with the local context (e.g. `backend/app/`, `backend/app/domains/`, `backend/db/`, `backend/evals/`, `frontend/src/`).
- **Keep docs in sync**: a change to routes, the node registry, enums, or the request flow must update the nearest README, this file's architecture section, and the relevant `docs/` file in the same change.

## Before Generating New Code

**Default to the smallest change that works, built out of code that already exists.** Both halves are load-bearing. This repo has repeatedly paid to *delete* layers that only forwarded a call — `db/stores/utils.py`, the parallel node dicts (`NODE_TYPE_TO_CLS`, `CATALOG_TIERS`, …), `preflight()`, `BookRecommendationOutput` — and each new one costs that removal again later.

**0. Start from the worked example, never from a blank file.** Two slices are the maintained templates, and every workflow in the app follows their shape: **`books/find_by_title/`** for a single-call node (parse args → build the query → count → preview → finalize), **`books/analyze_recommend/`** for a multi-step node — `executor.py` is the flow with numbered steps, one satellite module per LLM call's pure half, `dependents.py` interprets upstream artifacts. Copy the matching one and edit; the layout, `@task` placement, request-builder convention (`build_*_request` as a module-level pure function) and the `finalize_result` claim are already decided there. The reading rule both follow is in `backend/app/domains/README.md`.

**1. Search before you write.** Before adding a function, model, constant or helper, grep for the one that already does it. The things that get reinvented most:

| Reaching for | Already exists |
|---|---|
| serialization, ids, timestamps, pricing | `airglider` — `to_serializable`, `remove_empty_values`, `strip_zero_token_usage`, `now_iso`, `uuid_8`, `cost_of`. `common/utils` **re-exports** these; never keep a second copy |
| counting / previewing / fetching / streaming books | `BookWorkflow` — `count_books`, `preview_books`, `materialize_books`, `stream_books`, `self.store` |
| anything derivable from an already-built query | `DeferredBookQuery` — `count_stmt()`, `materialize_stmt()`, `compose()`, plus `compile_sql` |
| "which nodes exist / which executor / what's in the catalog" | `REGISTRY` — it answers from `SPECS` alone; never a module-level dict beside it |
| an LLM call from inside a node | `AppWorkflow.run_llm_args_parse` / `run_llm_tool_calls` |
| a book model with fewer fields | `Book` — narrow at the point of use (`model_dump(include=...)`), never a new class |
| a path, a limit, a model name | `config/constants.py` / `settings` — no literals at the call site |

**2. Take the smallest rung that fits.** The `@task` ladder in `backend/app/domains/README.md` (pure function → `run_llm_*` helper → `@task` method → full `Workflow`) is the specific case of a general rule: prefer a function to a class, a method on the object that already owns the data to a new module, a field to a subclass, a default to a flag. Add the next rung only when the current one demonstrably cannot carry the work.

**3. Don't build for a caller that doesn't exist.** No parameter with one value, no flag with one branch, no base class with one subclass, no "we'll need this later." `ParsedInput` is the standing example of the exception being *documented rather than spread*: it exists for PlanJane alone, and new slices are told not to pre-build it.

**4. Reuse means calling what exists — not hoisting new shared abstractions.** Some duplication here is deliberate and must survive: each slice writes its own `build_arg_parser_request` (so one node can change model or prompt without a flag on a shared base), `planjane/dial/` imports nothing from `app/`, and `airglider/` imports nothing from the app at all. Before factoring two things together, check that they are the same thing rather than two things that currently look alike — and that the merge doesn't cross one of those seams.

**5. Removal is part of the change.** If an edit makes a function, field, test or doc paragraph dead, delete it in the same change instead of leaving it for later; a codebase this size has no room for a deprecated tier. Say what you removed when you report the work.

## Files to Avoid Reading

To save tokens, do not read these unless the task specifically requires it:

- **Log files** (`backend/logs/` — `*.log` and chat-run JSON dumps): skip unless the task is formatting or restructuring the logs themselves.
- **SQL backups/dumps** (`backend/data/*.sql`, e.g. `backup.sql`; `backend/evals/results/**/*.sql` raw eval dumps): never read these. The schema init SQL in `backend/db/schema/` (extensions/tables/indexes) is fine to read.
- **`backend/playground/app_mock/`** — **outdated, ignore.** The mock executors and extended node schemas were the stand-in used for eval testing before the slices had real executors. They are no longer maintained and nothing live reads them (`NodeSpec.executor` points at the real slice executors). Don't read them for context, don't update them alongside a change to the real code, and don't model new code on them.

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

### Triage → PlanJane → TaskRunner

Three layers, one per question, each an `AppWorkflow` with its own envelope in the trace tree:

1. **`Triage`** (`app/orchestration/triage.py`, `TriageWorkflow`) — decides *whether to plan at all*: replay a cached plan, answer small talk, refuse out-of-scope, or hand the turn to the planner. It lives in `orchestration/` rather than `domains/` because it is not a capability — nothing in `EXECUTORS_CLS_MAPPING` will ever point at it, and its only domain knowledge is which planner to call. It is a workflow rather than methods on `Orchestrator` because `Orchestrator` owns no envelope: folding it in would mean a cache hit or a refusal produced no step in the trace.
2. **`PlanJane`** (`app/domains/planjane/`, `PlanJaneExecutor`) — *the planner*. Sends the user message to the LLM with the whole tool catalog (descriptions come from docstrings on the node request-schema classes) and returns goals with ids. It also **owns plan presentation**, and is the only thing in the app that renders a Mermaid diagram at all: `send_mermaid` stamps it onto `PlanJaneOutput`. The whole stack lives in `planjane/dial/` — `mermaid.py` turns goals into `MermaidBox`es (what a box says, plus the `depends_on` → `sent_to` inversion), `format.py` turns boxes into the string (markup, orientation, emission). **`dial/` imports nothing from `app/`** — only `airglider`, which is itself standalone — because PlanJane is headed for being a service of its own, and this is the corner already free to travel. Keep it that way when editing. Split three ways, matching the slice layout used elsewhere: `external.py` (`SystemGoal`, `PlanJaneOutput`, `ExecutionOrder` — what the plan *is*, and what triage and the task runner import), `schemas.py` (`GoalParseRequest`, `MAX_SYSTEM_GOALS` — what the LLM fills in), `executor.py` (`PlanJaneExecutor` — what runs). The dependency runs `external ← schemas ← executor`; import from the `planjane` package root rather than any of the three.
3. **`TaskRunner`** (`app/orchestration/task_runner.py`) — executes the plan. Its input is `TaskRunnerInput(plan: PlanJaneOutput)` and nothing else — no `query`, because the plan drives all of it, and never a `TriageOutput`: the runner executes plans and should not know a triage layer exists. `Orchestrator` is the one place the two are wired together, which keeps that import pointing downward.

Each capability is a **vertical slice** — one folder under `app/domains/<domain>/<node>/` holding its label, its request/input/output schemas and its executor, exporting a single `NodeSpec` (`app/domains/node_spec.py`). The three schemas are distinguished by who fills them in: `request` by the planner LLM choosing the capability, `input` by the task runner assembling the goal text and upstream outputs, `output` by the executor. (`request` and `input` converge eventually — the parsed args are an input the node currently produces for itself.) A domain's `guide.py` lists its specs; `app/registry.py` composes those into `SPECS` and hands that tuple to one **`Registry`** (`REGISTRY = Registry(SPECS)`). **The specs are the registry's only state**: it indexes them by `node_type` once, rejects duplicates, and answers everything else as a read over that index — `spec()` / `request()` / `executor()` / `executors()` / `in_tier()`, `node_type in REGISTRY`, `catalog_entries()` / `format_catalog()`, `node_type_enum`, `request_union()`. Lookups take a `NodeTypeEnum` member or a plain string, so no caller reaches for `.value`. The parallel module-level dicts are gone (`NODE_TYPE_TO_CLS`, `CATALOG_TIERS`, `RETRIEVAL_CLASSES`/`ANALYZE_CLASSES`/`REQUEST_CLASSES`, `AnyStrategyRequest`, `EXECUTORS_CLS_MAPPING`) — each rebuilt the same spec relationship from a different angle, which is how a node could be present in one and missing from another. Schemas describe *what* to do; **executors** (the *how*) subclass `AppWorkflow` and are reached through the spec. To see what the planner is actually told it can do at any moment, run `make tools-catalog` rather than trusting a checked-in snapshot: it renders the live registry.

**Adding a new capability:** see the step-by-step recipe **and the "Writing an executor — the rules" section** in `backend/app/domains/README.md` (new slice folder → request schema with LLM-facing docstring → `SPEC` → one line in the domain's `guide.py` → eval cases; the rules cover the parse → work → finalize body, the `@task` ladder, and the `finalize_result` claim). The planner picks it up automatically via the tool-loading step. The V1 node set is a settled decision: [docs/design/node-taxonomy-v1.md](docs/design/node-taxonomy-v1.md).

### Request Flow

1. **Frontend** sends a chat message via SSE to `POST /session/{id}/message`
2. **`Orchestrator`** (`app/orchestration/orchestrator.py`) — transport lifecycle only: SSE, timeouts, cancellation, recording. Builds a `RequestContext` and delegates to `TriageWorkflow`
3. **`Triage`** decides whether to plan, and calls **`PlanJane`** if so; the plan then travels to **`TaskRunner`** as an artifact
4. Results stream back to the client via **SSEStream** (`app/common/sse_stream.py`)

**Package layering is one-directional** and worth keeping that way: `app/common/` (messages, sse_stream, `RequestContext`) ← `app/domains/` (AppWorkflow, nodes, planjane) ← `app/orchestration/` (Orchestrator, Triage, run_recorder). `RequestContext` sits in `app/common/` because every layer reads it; it used to be in `app/orchestration/`, which made those two packages import each other.

**Current state:** `TaskRunnerWorkflow` (`app/orchestration/task_runner.py`) executes the classified strategies against the real executors, for the node types registered on this branch. It brackets each node with `task.start`/`task.end` SSE events so the UI can render one collapsible section per step (count in the header, preview cards inside); see `frontend/src/README.md`. Conversation is **single-turn**: each request is processed statelessly (turns are recorded to `chat_runs` but never read back).

### API Surface

`GET /health` · `GET /ping` · `GET /ready` — health/readiness. `POST /session/new` — mints a session id. `POST /session/{session_id}/message` — SSE chat. `GET /chat_runs` — review queue (least-reviewed first). `PUT /feedback/review` — upsert one review per (chat_id, session_id). `GET /feedback?chat_id=` — list reviews for a run. That is the whole surface — there is no `/add_feedback` and no `/chat_runs/tests`. No auth exists yet (pre-deploy blocker, docs/backlog.md).

### Workflow / Operation Pattern — the `airglider` library

**`backend/airglider/` is a separate project living in this repo** — a self-contained tracing/result library (extracted from the old `common/operation.py` + `common/workflow.py`) that will eventually be lifted out as its own distribution. **Read [backend/airglider/README.md](backend/airglider/README.md) before writing a `Workflow` or `@task`, or before editing anything under `airglider/`.** Its "The rules" section is the contract — instrumentation, `ok` semantics, the two step verbs, `StepFailure` — and it is not restated here, so this file cannot drift from it.

The four facts that concern *this app*:

- **Always import from the package root — `from airglider import OperationResult, Workflow, task`.** Never reach into `airglider.src.*`. `airglider/__init__.py` is the whole public surface; a symbol not re-exported there is not API (adding one means adding it to that file's `__all__`).
- **airglider imports nothing from the app**, which is what keeps it extractable — preserve that when editing. It therefore owns the serialization/identity helpers its record tree is built from (`to_serializable`, `remove_empty_values`, `strip_zero_token_usage`, `now_iso`, `uuid_8`) and the model price table (`airglider/src/config.py`, moved from the old `config/pricing.py`). `common/utils` **re-exports** those helpers rather than keeping a second copy, so importing from either place gets the same function.
- **Its tests live in `airglider/tests/`**, not under `tests/` — `make tests-airglider`, folded into `make tests-all`.
- **`BaseLLMRequest.to_summary()` (`clients/base.py`) exists because of `record.input`.** Every unit of work stamps its arguments before running, and a value's own `to_summary()` wins over a full dump — so without that method every prompt and message list would land in `chat_runs`, which is exactly what `save_payload` already gates. Give any large payload a `to_summary()` and it collapses everywhere at once.
- **`clients/` is tracing-free** — headed for standalone like airglider, so no `@task` lives there: client methods raise and return payloads, and `AppWorkflow`'s thin wrappers (`llm_execute`, `get_embeddings`, `execute_tool_call`) are where a client call becomes a step, gets its failure captured, and has its `token_usage` promoted. Its one airglider import is the `TokenUsage` data shape (fine — airglider is standalone too); the one remaining app import is `SSEStream` on `BaseLLMRequest`, the known last coupling (see the TODO in `clients/base.py`).

The app's own layer on top is `AppWorkflow` (`app/domains/base_workflow.py`), which adds SSE helpers and `finalize_result(ok=…)`; see the naming ladder under Domain / Node Type System below.

### Domain / Node Type System

`app/domains/` defines what the system can do:

- **The book node set.** The V1 taxonomy is `Retrieve_by_ISBN13`, `Retrieve_by_Title`, `Retrieve_by_Author`, `Retrieve_by_CoAuthors`, `Retrieve_by_Genre`, `Retrieve_Random`, `Combine_Union`, `Combine_Intersect`, `Filter_Retrieval`, `Analyze_Compare`, `Analyze_Recommend`. **On `minimal_end_to_end_v1` only `Retrieve_by_Title` and `Analyze_Recommend` are registered** — the rest are parked while the end-to-end path is built, so the rules below describe the target taxonomy, not what the planner can currently emit. `make tools-catalog` prints what is actually live. Each retrieval node is single-dimension (no cross-column filtering) and single-valued — one title, one author, one genre per node; several authors' separate bibliographies means several `Retrieve_by_Author` nodes. `Retrieve_by_CoAuthors` is the one multi-value node and means joint works only (2+ authors ANDed onto the same book), not a combined bibliography — see [docs/design/node-taxonomy-v1.md](docs/design/node-taxonomy-v1.md). `Retrieve_Random` is the one node that carries a full `BooksFilter` (a random pick has no dimension to be single about); it serves the bare "recommend me a book" **alone**, with no `Analyze_Recommend` after it, and `Filter_Retrieval` may never depend on it — bounds on a surprise go in its own `filters`. Cross-dimension requests are expressed by composition instead: the **combine tier** (`Combine_Union` = OR, `Combine_Intersect` = AND, `Filter_Retrieval` = metadata narrowing) consumes prior retrieval output and never queries the database. Pooling is also implicit — several task ids in one `depends_on` are pooled (OR) by definition — so `Combine_Union` is only used when that pooled set is an explicit step something downstream consumes — see [docs/design/execution-pipeline-v1.md](docs/design/execution-pipeline-v1.md). This domain's specs are listed in `app/domains/books/guide.py`; `app/registry.py` composes it with the other domains.
- **`NodeTypeEnum`** — the flat enum of every registered capability name plus `unknown`, built once in `Registry.__init__` and re-exported at module level as `NodeTypeEnum = REGISTRY.node_type_enum`. It stays module-level because it is a *type*: `SystemGoal.target_node_type` is annotated with it at class-definition time, which is also why the registry builds it once rather than per call. It is the constraint the planner LLM emits under. `unknown` is a member on purpose: it lets the model decline rather than pick a wrong capability, and `planjane/executor.py` refuses that goal with a reason instead of failing the whole tool call.
- **Shared output shapes** — `app/domains/books/external.py` (`BookRetrievalOutput`, `BookRequestContext`), over `Book` and the shape vocabulary in `app/domains/books/schemas.py`. `external.py` is what the layers outside the domain import, and is why a downstream node's `NodeInput` can declare `list[BookRetrievalOutput]` without reaching into a slice. A node's own output subclasses the shape its docstring claims in `Returns:`; `BookRecommendationOutput` is gone — the recommend slice subclasses `BookRetrievalOutput` directly and adds the one field that shape does not have. **`BookRetrievalOutput` carries `num_books` + `query` and no rows at all**: a retrieval node counts and hands on the query, so nothing downstream has a capped list of rows to reach for instead of composing. Rows exist in exactly two places — a preview streamed to the browser and dropped (`BookWorkflow.preview_books`), and `RecommendationOutput.books`, which is a node's *answer* rather than a sample of its match. `Book` is the single book model — every `books` column except `embedding` — and stays that way on purpose: narrow at the point of use (a prompt renderer picking fields, `model_dump(include=...)`), never by declaring a smaller model.
- **Domain base workflow** — `app/domains/books/base_workflow.py` (`BookWorkflow`), one layer under the domain-agnostic `AppWorkflow` (`app/domains/base_workflow.py`).
- **One call shape — `run(node_input)`.** Every unit of work in the app takes one argument: its own `WorkflowInput` subclass (`app/domains/node_input.py`). A node declares that class and lists it on `NodeSpec.input`; the task runner assembles it with `build_input(spec.input, goal.description, dependency_outputs)`. **The declaration is the point, not the typing.** It replaced `(query, artifacts: dict[str, Any])`, which could tell a node something was missing but never *what* — so a node short of a dependency could only raise. `RecommendInput.anchors: list[BookRetrievalOutput] = []` is a named, visibly unfilled slot: enough to fall back on the goal text today, enough to ask the planner for a goal that fills it later. Default a field whenever the node has a real fallback; require it only when the node cannot proceed. **Fields are filled by type, never by key** — `X` takes the first match, `X | None` takes it or None, `list[X]` takes all; keys are provenance. A required field that matches nothing raises `ValidationError` *naming the field*, which `TaskRunnerWorkflow._prepare` turns into one skipped goal. **Services are not constructor arguments and are not on the input** — `AppWorkflow.__init__(ctx, messages)` is the only `__init__` in the app layer, and `sse_stream`/`llm_client`/`app_env`/`session_id`/`user_message` are properties off the `RequestContext`. Context and input split on lifetime: services are built once per HTTP request, an input per dispatch.
- **A node declares its services view too, as `NodeSpec.context`.** `RequestContext.stores` is a `dict[type, BaseStore]` — the opaque carrier that lets `app/common/` hold a `BookStore` without importing the books domain — and a domain turns it into a typed field with a `narrow()` classmethod: `BookRequestContext.narrow(ctx)` resolves `store` once, at dispatch, so a request missing it fails there (naming the store) rather than at the first query. `BookWorkflow.store` is then a plain field read. The route builds the widest context; only the task runner narrows, because it is the first place that knows which node is about to run. The stores are constructed on the FastAPI request-scoped session — never rebuild them from `ctx.session_factory`, which opens a different session and silently splits the transaction.
- **Naming (`Workflow` / `Executor`)** — the ladder is `airglider.Workflow` → `AppWorkflow` (`app/domains/base_workflow.py`) → `BookWorkflow` (`app/domains/books/base_workflow.py`). Concrete units of work are `*Workflow` too (`TriageWorkflow`, `TaskRunnerWorkflow`). **`Executor` is the subset of those the planner can dispatch** — a node with a request schema, a `NodeSpec` and a catalog entry, reached via `REGISTRY.spec(...).executor` instead of called directly. Node vs. pipeline step is what the second word carries. (The old "`Base` marks a reusable base class" rule is retired — see `backend/app/domains/README.md`.) `BookWorkflow` carries `count_books(query)` and `preview_books(query)` — both `@task`s: the first stamps `query`/`query_sql`/`num_books` on the output and fetches nothing, the second hands back a few rows for the caller to stream and drop — plus `materialize_books()` (pool upstream queries into one anchor and fetch its rows) and `stream_books()`, which validates through `BookOut` before anything reaches the browser. The counting/fetching pair replaced a single `preflight()` that returned `(total, sample)` from one round trip; splitting them is what let `BookRetrievalOutput.books` go away.
- `app/registry.py` — `Registry` answers every node lookup from `SPECS` alone

### Database

- **PostgreSQL + pgvector** via async SQLAlchemy (`db/async_engine.py`)
- Schema SQL in `db/schema/` (extensions → tables → indexes)
- SQLAlchemy models in `db/schema/models.py`
- Repository pattern in `db/stores/` — `book_store.py` is the primary store. Retrieval is **counts-first**: `title_query()` builds a `DeferredBookQuery` that isn't run for rows, `count()` runs only a `COUNT`, `DeferredBookQuery.compose()` folds several into one CTE, and `materialize()` is the single place rows are fetched — at the end of a plan. Statement derivation lives on `DeferredBookQuery` itself; the store builds from dimensions and executes. See `db/README.md` and [docs/design/execution-pipeline-v1.md](docs/design/execution-pipeline-v1.md)
- `db/ingestion/` populates books from `data/books.csv` — **legacy, ignore**: still uses old `Workflow`/`@task` patterns and will be reworked later; don't refactor it or model new code on it

### Config

- Model rates are **not** here — they moved to `airglider/src/config.py`; import via `from airglider import cost_of, PRICES_CHECKED_ON`
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
