# Backlog

**Updated:** 2026-07-17 · Migrated from `backend/TODO.md` and `frontend/TODO.md`
(which are now short-lived scratchpads — durable items live here).

**How to read this file:** items are tiered **P1** (before/with the V1 ship — most also
appear in [roadmap.md](roadmap.md) phases), **P2** (post-V1 candidates), **P3**
(someday/cleanup). `file:line` references are from the 2026-07-10/12 review passes;
line numbers may drift, the file and symbol names are the stable part.

## Security & pre-deploy (P1 — roadmap Phase 5)

- **`GET /chat_runs` has no auth** (`app/api/routes/chat_run.py`) — no auth dependency,
  and no auth middleware anywhere in `app/main.py`. Returns `ChatRunModel.to_dict()`
  for every row unscoped: full user_message/assistant_message/session_id plus the
  planner/tasks/sse_events JSONB traces, paginated via limit/offset. Anyone can page
  through the entire chat history of every user with a plain GET. Gate it as an
  internal/admin route at minimum before it's reachable from the internet. (For dev,
  fetching all chat_runs is fine; prod likely wants it limited to test suites.)
- **Feedback endpoints have no ownership check** (`app/api/routes/feedback.py`) —
  `GET /feedback?chat_id=` and `PUT /feedback/review` take caller-supplied
  chat_id/session_id and the store just queries/upserts whatever is passed. Combined
  with the chat_runs disclosure both IDs are trivially harvestable, so anyone can read
  or silently overwrite another reviewer's feedback. Needs real session-ownership
  verification, not "the ID is hard to guess".
- **CORS**: `allow_methods=["*"]` with a TODO at `app/main.py:57` — tighten before deploy.
- **`uuid_8()` id length** (`common/utils/identifiers.py`) — 8 hex chars is only 32 bits
  (~4.3 billion values), used as the primary key for `chat_runs.chat_id` and
  `feedback.id`. By the birthday paradox there's a ~50% chance of a collision after
  ~77k rows, and a collision is a silent failed insert. Switch to a longer id before
  real traffic.
- **`FeedbackIn.message` has no max_length** (`app/api/schemas/external.py`) — also move
  `ChatIn`'s ad-hoc length check from the route into the schema for consistency.

## Reliability (P1 — discovered during Phase 2 eval runs)

- **OpenAI TPM rate limit hit under concurrent suite runs** — after the Phase 2 docstring
  expansion (fuller `Purpose/Args/Returns/.../Example queries` catalog entries, larger
  `StrategyRequest` tool schemas), running the eval suites concurrently (`make
  query-suite-all`) trips OpenAI's tokens-per-minute limit; several `run ok: ❌` rows in
  the eval report reflect this (eval report commit `9d0e402`,
  `backend/evals/results/7_18_nodes_description/`). Three options, not yet decided:
  (1) leave as-is and surface a user-facing "rate limited, try again" message — cheapest
  to ship but the user feels it directly; (2) exponential backoff/retry on the OpenAI
  client call — smooths over transient limits but adds latency and isn't guaranteed to be
  enough under real concurrent load; (3) request a higher TPM tier from OpenAI — solves it
  structurally but is an account-level fix, not a code fix, and doesn't help local/free-tier
  dev. Needs a decision before V1 production traffic.

## Correctness (P1 = ship-blocking, otherwise P2)

- **P1 — Frontend double-session race** (`ChatBot.jsx` mount-time `initSession()` +
  `handleSendMessage`'s fallback `createSession()`) — both can fire if a message is sent
  before the initial session promise resolves; two sessions created, last `setSessionId`
  wins silently. A shared `useSession()` hook fixes this and the duplication at once.
  *(Roadmap Phase 6.)*
- **P1 — Unreachable 3-minute timeout** (`api.js` internal 120s timeout vs `ChatBot.jsx`
  180s safety timer) — the 3-minute timeout message can never fire. *(Roadmap Phase 6.)*
- **P2 — IssueReportModal listener leak** — every `ChatRunRow` mounts its own modal
  unconditionally, each registering a permanent mousedown listener (up to ~200 live
  global listeners). Mount only when open, or share one modal.
- **P2 — Semaphores bug (investigate)** — concurrency issue seen during suite runs; also
  try lowering the semaphore limit and observe. Pairs with the concurrency/timeout test
  item below.
- **P2 — Review page doesn't distinguish error types** (`frontend/src/pages/ChatReviewPage.jsx`
  `ChatRunRow`) — the negative badge and "Planner envelope" detail both key off one flat
  `run.planner?.runtime_error`/`.message`. A genuine unhandled exception in the workflow
  and a child step's `StepFailure` aborting upward currently stamp the exact same
  `runtime_error` field (`backend/common/workflow.py` — an interim fix; the fuller
  discriminated-union error redesign was deliberately deferred), so both render
  identically in the UI. A reviewer can't tell "the workflow itself crashed" from "a step
  under it failed" without opening the raw JSON envelope. Needs either a backend-side
  error-kind field to key off of, or at minimum a distinct label/color derived from
  what's already in `errorDetail` (e.g. exception class parsed from the traceback).

- **P2 — Undecided: how `Analyze_Compare` chains with single-book analyze nodes.**
  `CompareStrategy` was re-registered 2026-07-18 for eval testing, which makes
  `docs/design/node-taxonomy-v1.md`'s "Removed from V1" section and `roadmap.md`'s
  Phase 1/deferred entries stale. Open design question (worked example: eval case
  `chat_e35fc1e0`, "Compare the themes of Pride and Prejudice and Jane Eyre"):
  retrieve→per-book-analyze→implicit synthesis in the final reply, vs.
  retrieve→per-book-analyze→explicit `Analyze_Compare` node depending on the analyze
  task ids. Full writeup in node-taxonomy-v1.md's "Future considerations" section.

## Performance (P2)

- **book_store per-author N+1** (`db/stores/book_store.py`) — `search_by_book_filter`
  loops one DB round-trip per author instead of one query + grouping (the filter already
  ORs across authors).
- **Per-char SSE streaming** (`app/common/sse_stream.py` `send_chars`) — one SSE event
  + `asyncio.sleep` per character; hundreds of tiny events and real latency on long
  responses. Chunk by word if latency becomes a complaint.
- **Dead `index=True` flags** (`db/schema/models.py` BookModel) — indexes are created by
  raw SQL, not `Base.metadata.create_all`, so the flags do nothing and filters on
  published_year/average_rating/genre run unindexed. Add real indexes or drop the flags.

## Test coverage (P2)

- **Stores**: zero tests for `book_store.py`, `chat_run_store.py`, `feedback_store.py`,
  `base_store.py` (`stores/utils.py` got SQL-injection regression tests 2026-07-12).
- **Routes**: only `chat_message.py` has a test; `session.py`, `chat_run.py`,
  `feedback.py`, `health.py` have none.
- **Domain schemas**: no tests for `app/domains/{books,project,users}/schemas/` validators.
- **Untested modules**: `common/context.py` (AppContext), `db/bootstrap.py`,
  `db/readiness.py`.
- **Concurrency & timeouts**: unit tests for semaphore behavior and workflow timeouts.
- **Integration tests**: build out the in-process faked-store pattern
  (`tests/integration/test_chat_runs_api.py` is the seed); split tests and eval queries
  cleanly by endpoint; structured inputs/outputs.
- **Frontend tests**: none exist. Priorities: markdown rendering edge cases (nested
  bullets, back-to-back dividers), error messages, backend down/stalling, font/spacing
  across scales.
- **Unit-test organization pass** (after DB-save + eval tests settle): review names and
  comments, add navigation markers/separators per file.

## Workflow framework (P2)

From the owner's design notes — these need real design thought, not drive-by fixes:

1. One executor for `@task` and workflow (unify the two call paths).
2. Timeouts supported inside `@task` and `Workflow` themselves.
3. Remove private attributes (keep state in the output; may need `create` instead of
   `parse`) — matters once buffers get loaded.
4. **Checkpoint gap**: interrupts work, but child-workflow progress is lost because
   steps are only appended *after* a child finishes (`run_async_step` → await → 
   `add_steps`). Better checkpointing needs incremental `add_steps` (append the child's
   `OperationResult` reference before running, let it mutate) — requires rethinking
   result append/overwrite semantics. *(Cross-referenced in roadmap deferred:
   checkpoint/resume.)*
5. `self.result` message overwriting is lossy — figure out message vs details; maybe
   push prior text to details as "prev message: …", and stop overwriting in
   app/workflow.
- Once resume/checkpoint exists: DAG processing may move into model validation so the
  orchestrator can pick up and continue; steps become config describing what runs next.

## Accessibility (P2)

- `IssueReportModal` — no `role="dialog"`/`aria-modal`, no focus trap, no initial
  focus, no Escape-to-close.
- Version dropdown + category dropdown — mouse-only open/close, no Escape, no
  `aria-expanded`/`aria-haspopup`.
- NavBar overlay/panel — closes on click only; no keyboard path, focus trap, or Escape.
- Chat textarea — accessible name relies on placeholder (disappears once typing
  starts); add an `aria-label`.

## Frontend refactors & tech debt (P2/P3)

- **P2** `useSession()` hook — dedupes session boilerplate (`ChatBot.jsx`,
  `ChatReviewPage.jsx`) and fixes the double-session race above.
- **P2** `useClickOutside()` hook — click-outside logic is copy-pasted 3×
  (version dropdown, feedback controls, chat input).
- **P3** Dead code: `api.js` `getTaskPlanDiagram` (diagrams come over SSE),
  `stopChatStream` (no backend endpoint — see roadmap deferred), and
  `getRecommendedBooks` (calls `GET /session/{id}/recommended_books`, which no longer
  exists server-side — found 2026-07-17); leftover debug
  `console.log`s (App.jsx, ChatBot.jsx, MermaidDiagram.jsx, VersionDropdown.jsx);
  `data/chatSuggestions.js` commented-out idea block.
- **P3** `formatAuthors`/`formatAuthorsMobile` (~90% duplicated) — collapse with a
  `compact` flag.
- **P3** Backend rename pass: `@task` → `@op_task` (avoid name conflicts),
  `OperationalResult` → `OperationResult`, workflow `self.result` → `self.op_result`,
  "issues" → "feedback" everywhere.
- **P3** `db/stores/base_store.py` prints compiled SQL with `literal_binds=True` — only
  book_store routes through it (no PII flows), but gate behind `logger.debug`.
- **P3** Make orchestration itself a workflow?

## UI polish pool (P2/P3)

- Scrollable sidebars; chat input scrollable/scrolls on first input.
- Mermaid viewport minimum height; long/short graphs under max concurrency — consider
  wrapping graphs into rows (g1, g2, g3 …).
- Mermaid font fixed at 14px — does it scale on small devices? Is the
  `user-scalable=no` viewport meta still needed with the new mermaid code? (Investigate.)
- Review page: align the preview; move praise/issue controls next to the submit button
  for a top-down flow; consolidate feedback/hints/colors into one area away from Send;
  better emojis/arrows.
