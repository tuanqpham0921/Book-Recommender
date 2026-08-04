# backend/app

The FastAPI application layer: HTTP surface, orchestration, and the domain node system.
Architecture overview lives in the root [CLAUDE.md](../../CLAUDE.md); V1 plans in
[/docs](../../docs/README.md).

## Layout

| Path | What it is |
|---|---|
| `main.py` | FastAPI app factory, CORS, router registration |
| `api/routes/` | One file per router (health, session, chat_message, chat_run, feedback) |
| `api/schemas/` | External request/response models (`ChatIn`, `ReviewIn`, …) |
| `orchestration/` | `Orchestrator` (entry point per message) + `RequestContext` |
| `domains/` | Node type system + planner pipeline — see [domains/README.md](domains/README.md) |
| `common/` | App-level workflow base, `SSEStream`, message types |
| `registry.py` | node_type → schema class mapping, capability catalog, executor mapping |

## API surface

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/ping` | Liveness |
| GET | `/ready` | Readiness (orchestrator + DB); 503 when not ready |
| POST | `/session/new` | Mints an env-prefixed session id (no server-side state) |
| POST | `/session/{session_id}/message` | The chat endpoint — streams SSE events |
| GET | `/chat_runs` | Review queue, least-reviewed first (`limit`/`offset`/`session_id`) |
| PUT | `/feedback/review` | Upsert one review per (chat_id, session_id) — see `ReviewIn` |
| GET | `/feedback?chat_id=` | List reviews for one run |

There is no auth yet — a known pre-deploy blocker (docs/backlog.md, Security P1).

## Request flow (current state)

1. `POST /session/{session_id}/message` → `Orchestrator.run` builds a `RequestContext`
   and delegates to `PlannerWorkflow` (`domains/planner/main.py`).
2. The planner parses intent → classifies strategies → streams a Mermaid task-plan
   diagram and the goal list over SSE.
3. `TaskRunnerWorkflow` (`domains/task_runner.py`) runs the accepted goals in dependency
   order against the **real** executors (`registry.py`, `EXECUTORS_CLS_MAPPING` →
   `NODE_EXECUTORS_CLS_MAPPING`), for the node types registered on this branch. It
   brackets each node with `task.start` / `task.end` SSE events — closed in a `finally`,
   so a node that raises still closes its UI section — and stamps the node's `num_books`
   onto the section header on close. Retrieval nodes report a count plus a few preview
   cards; only the terminal node fetches the full rows.
4. Every turn is recorded to the `chat_runs` table (planner/tasks JSONB) —
   that's what the review page and eval reports read. Requests are stateless: nothing
   reads prior turns back (single-turn by design for V1).
