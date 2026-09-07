# Backlog

**Updated:** 2026-09-07 · Migrated from `backend/TODO.md` and `frontend/TODO.md`
(which are now short-lived scratchpads — durable items live here). The 2026-09-07 pass
swept `backend/TODO.md` against the code: what was already built was deleted, what was
decided the other way is under "Settled", and the rest landed in the sections below or in
`design/`.

**How to read this file:** items are tiered **P1** (before/with the V1 ship — most also
appear in [roadmap.md](roadmap.md) phases), **P2** (post-V1 candidates), **P3**
(someday/cleanup). `file:line` references are from the 2026-07-10/12 review passes;
line numbers may drift, the file and symbol names are the stable part.

## Security & pre-deploy (P1 — roadmap Phase 5)

- **`GET /chat_runs` has no auth** (`app/api/routes/chat_run.py`) — no auth dependency,
  and no auth middleware anywhere in `app/main.py`. Returns `ChatRunModel.to_dict()`
  for every row unscoped: full user_message/assistant_message/session_id plus the
  planner/tasks JSONB traces, paginated via limit/offset. Anyone can page
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

  **Capacity arithmetic** (owner's note, graduated from `backend/TODO.md` 2026-09-07):
  each node parses its own arguments, so one plan is roughly 15 requests. At the 500 RPM
  tier that is ~33 concurrent turns before throttling — and less in practice, since the
  requests arrive in bursts per step rather than evenly. The next tier (5,000 RPM) takes
  the pressure off entirely, which is what makes option (3) above the cheap answer.
  Per-node parsing also *saves* calls when an upstream goal fails: the runner skips the
  dependent goal, and its parse never happens.
- **Pooled DB connections are being reclaimed by the garbage collector** — observed during
  suite runs, logged repeatedly as `SAWarning: The garbage collector is trying to clean up
  non-checked-in connection <AdaptedConnection …>, which will be terminated` from
  `sqlalchemy.pool.impl.AsyncAdaptedQueuePool._finalize_fairy`. A session is being dropped
  without `close()` or a context manager, so the connection is not returned to the pool and
  is torn down instead of reused. Under load that silently shrinks the pool. The stores are
  built on the FastAPI request-scoped session (`db/async_engine.py` `session_factory`,
  `pool_size=MIN_CONNECTIONS`), so the leak is most likely a path that opens its own session
  — check the eval runner and any `session_factory()` call outside the request scope.
  Graduated from `backend/TODO.md` 2026-09-07, where it sat as a raw log paste.

## Planner quality (P2 — from the 2026-07-24 TODO sweep)

Shape-level planner questions live in
[design/planner-shape.md](design/planner-shape.md); these are the concrete work items.

- **Small talk and gibberish become system goals.** They should be filtered before the
  goal stage — a pre-check that classifies small talk / gibberish, or rewords a
  continuation query, rather than letting the goal generator invent a node for "hello".
  Overlaps with the clarification node (roadmap Phase 1): decide whether this is a cheap
  pre-classifier or just another thing the clarification node handles.
- **The prompt-injection / preflight parse is not well designed or tested.** It needs its
  own tests *before* more nodes are added, and it matters more inside nodes than in the
  planner — a node's arguments are where an injected string actually lands. (A pre-check
  node was tried and reverted in commit `ed34d95`.)
- ~~**A similarity ask with a quantitative constraint has nowhere to put it.**~~ **Fixed
  2026-08-24.** "Books like Dune but under 300 pages" is now `Retrieve_by_Title` →
  `Analyze_Similar_Books`, plus `Retrieve_by_Numeric_Traits`, joined by `Combine_Intersect`.
  The premise of this item — that a bound cannot move to a narrowing node because filtering
  a ranked pool throws the ranking away — was a property of materialized *rows*, not of a
  scored deferred query: `compose(op="and")` carries the pool's cosine `score` through and
  `materialize_stmt` orders by it. `embedding_search_stmt.filters` was deleted rather than
  kept waiting. What remains is a phrasing gap, not a routing one: the count after such an
  intersect means "of the 250 nearest, N also match", and no node says so out loud. See
  [design/node-taxonomy-v1.md](design/node-taxonomy-v1.md) (2026-08-24).
- **`Retrieve_by_Title` should prefer exact matches when there are any.** `title_query`
  keeps every row where `title ILIKE '<t>'` **or** trigram similarity > 0.7, so a catalog
  holding several editions of one book returns all of them. That is fine for a lookup and
  expensive for an anchor: `Analyze_Similar_Books` refuses past `MAX_ANCHOR_BOOKS` (5), so
  six editions of one title fail "books like X" — a failure that looks like the node's and
  is the query's. Fix in `title_query` (exact arm first, trigram only when it finds
  nothing), which fixes every consumer at once. The cap stays regardless: a plan naming six
  *different* books is still six books. `check_anchors` logs the pooled total every run, so
  the traces say how often this actually fires.
- **Embedding experiments** (`book_store.search_by_embedding` already exists): how closely
  do single-word genre and author embeddings score against near misses, and can a composed
  record embedding ("title, page count, description …") answer "find books with 100 pages"
  without the structured filter path?

The three below graduated from `backend/TODO.md` 2026-09-07.

- **`confidence` comes back as 0.0 on some goals, unexplained.** `SystemGoal.confidence` is
  a real gate — `planjane/executor.py` rejects a goal below the tuning threshold with
  "confidence too low" — so a spurious 0.0 silently drops a goal that was otherwise fine.
  Not yet known whether the model is genuinely unsure, is omitting the field and getting a
  default, or is anchoring on an example. Worth a pass over recorded runs before tuning the
  threshold, because the two causes want opposite fixes.
- **No worked example of an analyze goal depending on another analyze goal.** The prompt's
  examples are all retrieval → analyze. A chain like `Analyze_Compare(a, b)` depending on
  `Analyze_Themes(a)` and `Analyze_Themes(b)` — or a similarity search seeded by a compare
  — has no example to imitate, which is one reason the compare chaining question
  ([design/node-taxonomy-v1.md](design/node-taxonomy-v1.md) Future considerations) is hard
  to test. Add examples when the analyze tier grows past one node; best-effort linkage at
  the node is the fallback the owner sketched, not a plan.
- **P3 — reasoning in the first person.** `SystemGoal.reasoning` reads as a third-person
  label; "I need to find this title first" is friendlier if it ever reaches the UI. Carries
  a caveat the owner already flagged: if `reasoning` is ever fed back into a re-parse,
  first-person text is a worse input than a neutral one, so this is only safe while the
  field stays display-only.

## Node contracts & refusal (P2 — deferred 2026-08-19)

Both items are written up in [design/node-refusal-v1.md](design/node-refusal-v1.md), with
the deferral criteria and what would say it's time. They share one root: **a node handed
work it cannot do has no way to say so** — only `ok=True` (I did the job) or a raise (the
code broke).

- **The args parser cannot decline.** `OpenAIParserRequest.to_payload`
  (`clients/openai_requests.py`) pins `tool_choice` to the one tool model, so the parse is
  mandatory: "give me a book about war" routed to `Retrieve_by_Title` yields
  `title="war"` and an `ok=True` count. Proposal: let the parser *choose* the tool; a
  declined parse becomes a refusal message and `ok=False` **with no runtime error**, which
  travels back to the planner for a clear out-of-capability reply. This amends executor
  rule 2 in `app/domains/README.md` ("never hand-set `ok=False` and return") — the amendment
  is the point, not an oversight. Deferred: with 3 of 11 nodes registered (`guide.py`),
  that query has no correct plan to find, so the mis-route is a catalog gap rather than a
  routing-quality bug.
- **`num_books == 0` is `ok=True`, which is right for the producer and wrong for the
  consumer.** An empty match is a real answer the reply should state — but a 0-count query
  composed into a downstream anchor is an OR branch that scans and returns nothing while
  making the anchor look populated. **Partly fixed 2026-08-18**: `ParsedDependents`
  (`app/domains/books/find_similar_books/dependents.py`) sorts 0-count anchors into a
  separate `empty` pile instead of pooling them, and `FindSimilarBooksExecutor.check_anchors`
  raises when all are empty. Remaining options — answer in the producing node, withhold empties in
  `TaskRunnerWorkflow._dependency_outputs`, or skip a node whose dependencies are all
  empty — interact with the missing generation node, so the last one is the one that
  survives it.

## Correctness (P1 = ship-blocking, otherwise P2)

- **~~P1 — `AnyStrategyRequest` union drift~~ — resolved 2026-08-10.** The hand-listed
  union is gone; `Registry.request_union()` builds it from the registered specs on
  demand, so the union and the registered node types are the same list by construction
  and cannot drift again. Nothing consumes it yet (`strategy_classification.py` was
  removed with the planner rewrite) — it exists for the human-in-the-loop resume path
  described below, which is what needed it. Original report, kept for the reasoning:
  `app/domains/planner/strategy_classification.py`) — the union has **10 members**;
  `NODE_TYPE_TO_CLS` has **28 registered node types**. `Analyze_Compare` (re-registered
  2026-07-18) and all 17 extension types are registered, planned, and executed but are not
  in the union that types `StrategyClassificationOutput.accepted/buffer/refused`.
  Verified 2026-07-24: building that model from a dict raises `ValidationError` for those
  types (`Input tag … does not match any of the expected tags`), and `model_dump()` emits
  `PydanticSerializationUnexpectedValue`, serializing them against
  `RecommendationStrategy`'s schema. It is latent today only because the workflow appends
  in place and pydantic does not validate `list.append`; field values survive by
  duck-typing. It becomes a hard failure the moment anything **reconstructs the output
  from JSON** — which is exactly what human-in-the-loop resume does
  ([design/human-in-the-loop.md](design/human-in-the-loop.md), blocker 1). Fix by deriving
  the union from the registry rather than hand-listing it, so the two cannot drift again.
- **P2 — Stale comment contradicts the code it sits on**
  (`app/domains/books/registry.py`) — the comment above the imports says `CompareStrategy`
  is "intentionally parked … out of `BOOK_ANALYZE_CLASSES` / `BOOK_NODE_TYPE_TO_CLS`",
  while the lines immediately below it put `CompareStrategy` in both. Same staleness as
  the roadmap/taxonomy notes; resolve together when Compare's fate is settled.
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
- **One round trip per count** (graduated from `backend/TODO.md` 2026-09-07) — a plan with
  three retrieval goals runs three separate `COUNT`s. Since every retrieval already hands on
  a composable `DeferredBookQuery`, several counts could be issued as one statement
  (a union of counted CTEs) instead of one per goal. Only worth it once a plan routinely
  carries several retrievals; `Combine_Intersect` made that shape normal, so it is closer to
  worth measuring than it was.

## Tracing, clients & tooling (P2)

Graduated from `backend/TODO.md` 2026-09-07.

- **A compact tracer mode.** The recorded tree is shaped for completeness, not for reading:
  a run's JSONB carries every step's input and output. `to_summary()` and `save_payload`
  already keep the worst of it out (see the airglider notes in `CLAUDE.md`), but there is no
  mode that *flattens* the tree or keeps only identifying fields (isbn13 + title, no parsed
  arguments). Wanted for eval review and for anything that reads runs back in bulk. Related:
  the review page can't tell a workflow crash from a child `StepFailure` (Correctness, P2) —
  both want the record to carry more shape, not more bytes.
- **`add_details(msg, log=True)`** — `add_details(*messages)` (`airglider/src/base_glider.py`)
  writes to the record only, so anything worth seeing live has to be logged separately, and
  the two drift. A flag would make "record it and log it" one call. Open question the owner
  attached: which details actually deserve a log line — the split today is that logging
  covers start/fail/end and details cover the pipeline, and a flag should not erode that.
- **Finish the migration to the Responses API** — `clients/openai_client.py` is currently
  split: parser calls go through `client.responses.create`, while streaming chat still uses
  `client.beta.chat.completions.stream`. Two request shapes and two response shapes to
  maintain, and the `beta.` prefix is the one likeliest to move under us. The blocker is that
  the streaming path is what pushes SSE deltas, so it is the more delicate half.

## Test coverage (P2)

- **Stores**: zero tests for `chat_run_store.py`, `feedback_store.py`,
  `base_store.py` (the deferred-query builders got SQL-injection regression tests
  2026-07-12; they live in `test_deferred_query.py` now that `stores/utils.py` is
  folded into `deferred_query.py`/`book_store.py`, 2026-08-17).
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
   steps are only appended *after* a child finishes (`parent_scope` attaches on the way
   out). Better checkpointing needs incremental `add_steps` (append the child's
   `OperationResult` reference before running, let it mutate) — requires rethinking
   result append/overwrite semantics. *(Cross-referenced in roadmap deferred:
   checkpoint/resume.)*
5. ~~`self.result` message overwriting is lossy — figure out message vs details.~~
   **Done (2026-08-07):** resolved by deleting `OperationResult.message` outright
   rather than making the overwrite lossless. Every layer (`@task`, `Workflow.__call__`,
   `run_async_step`, `finalize_result`, each workflow's own `success_message`/
   `failure_message`) wrote the field and nothing read it back — not the API, not
   `record_chat_run`, not the review page, not the eval reports — so the "lossy
   overwrite" only ever destroyed text no consumer saw. Free-text now goes in `details`
   via `add_details`, and failure text is on `runtime_error.message`, which *is* read
   (review page, `report.py`).
6. **Retries above the API layer** (graduated from `backend/TODO.md` 2026-09-07). Today
   everything is one pass: verified 2026-09-07 that no retry or backoff exists anywhere in
   `app/`, `clients/`, `airglider/` or `config/`, and that `AsyncOpenAI` is constructed with
   nothing but an api_key (`clients/openai_client.py`) — so the only retrying in the system
   is the OpenAI SDK's **own default** (`max_retries=2`, transport errors only), which this
   repo neither sets nor tunes. Worth deciding deliberately rather than inheriting; the same
   constructor also sets no client-level `timeout`, while the orchestrator enforces its own.
   A *business* retry is a different shape: the unit that would
   repeat is `llm_args_parse → post-process → store to output`, and repeating it means
   wrapping that trio in its own `OperationResult` so each attempt is visible in the trace
   rather than overwriting the last. The owner's framing: the workflow holds the retries,
   and the **parent** decides the re-write — a node that failed to parse should not be the
   thing that reworded the query. Pairs with the rate-limit decision under Reliability,
   where option (2) is exactly this at the transport layer.
7. **Is `@task` idempotent, and does re-entering one distort its timing?** An open question
   from the owner's notes, unresolved: `@task` overrides the `OperationResult` returned to
   the decorator, so a step that runs twice may report a duration measured from the wrong
   start. Matters for retries (item 6) and for resume (`human-in-the-loop.md` blocker 2) —
   both replay a step that already has a record. Worth a test before either is built.
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
- Book cards: edge-triggered horizontal auto-scroll (the row scrolls while the pointer
  rests near either end), and lift the card on hover. *(From `frontend/TODO.md`,
  2026-09-07.)*

## Ideas pool (P3 — not scheduled, kept so they aren't re-derived)

Graduated from `backend/TODO.md` 2026-09-07. None of these are planned; each is here
because the reasoning was worth more than the line it sat on.

- **A "why?" button on a recommendation.** The cards already know their isbn13s, so a
  per-book "why this one?" could call the compare/analyze node **directly**, skipping the
  planner entirely — a fixed capability with a fixed input needs no plan. Costs one DB
  round trip per press before any caching. This is the cheapest possible version of
  multi-turn: an interaction that continues the turn without reopening the conversation.
- **Analyze nodes that call the planner themselves.** Expose the action nodes (compare,
  similar-books, single-book Q&A) as entry points, and let each ask the planner for the
  retrieval it needs rather than depending on goals the planner wrote up front. Attractive
  because a node knows its own gaps; expensive because *"recommend books like A and B, then
  compare A and B"* becomes two independent planner calls over the same books, with
  duplicated retrieval and a race to resolve the same entities. An entity classifier that
  caches resolved books would be the prerequisite. Closely related to
  [design/planner-shape.md](design/planner-shape.md) open experiment 4.
- **A bounded multi-turn control loop.** Rather than one plan per turn: loop
  `plan → run → reword`, feeding the reworded state back in, capped at ~10 goals per
  iteration, with a final internal summary ("recommended isbn13 …, the user wanted to
  pause"). Keeps the agentic shape without an unbounded loop. Wants the conversation work
  in the roadmap's V1.1 flagship first — and note the guardrail in
  [design/human-in-the-loop.md](design/human-in-the-loop.md): nothing may stay alive between
  iterations.
- **A narration field on operation records.** A short natural-language line per unit of
  work — "searched similar books with {filters}, took 10s, N tokens" — as a first-class
  field rather than reconstructed from the tree. Would feed both generation and the review
  page. The owner's own hedge is worth keeping: it may just be a function over the record
  written where it is needed, not a stored field.
- **Pre-made plans for common shapes.** `find title → similar books → write`, and the bare
  "recommend me something", are stable enough to cache as plans and skip the planner call.
  Two caveats already noted: it is the same idea as branching inside a node (planner-shape
  experiment 4), and it does nothing for the slow half — the analyze + embed step is where
  the time goes, and it is not cacheable across queries.
- **A unified reference/artifact renderer.** Mermaid is currently the only thing the app
  renders *about* a run. The same treatment — a name, a description, and a body — would let
  any node hand the UI a displayable artifact (a comparison table, an ideal-book
  description) without each one inventing its own SSE event.

## Settled — recorded so they aren't re-opened

Each of these appeared in `backend/TODO.md` as an intention and was decided the **other**
way. Kept short; the code and `CLAUDE.md` are the real record.

- **Stores take a request-scoped session, not a session factory.** The TODO wanted
  `BookStore` to hold a factory and open a session per query. It takes an `AsyncSession`
  (`db/stores/base_store.py`), built once per HTTP request — rebuilding from
  `ctx.session_factory` opens a second session and splits the transaction.
- **Each node parses its own arguments in its own call**, rather than one combined parse in
  the task runner. Separate parses cost more requests (see the capacity note under
  Reliability) and buy per-node prompts, examples and model choice — plus a parse that never
  happens when an upstream goal fails.
- **Numeric bounds go inside the search, not after it.** The TODO's sketch was
  embedding → filter by isbn13. `filter_books` and `BookStore.filter_query` were deleted
  2026-08-24: a bound is `numeric_traits_query()` composed with the subject via
  `Combine_Intersect`, and `compose(op="and")` carries the cosine `score` through so
  ranking survives the narrowing.
- **The similarity floor is `MIN_SIMILARITY = 0.35` with a 250-book pool cap**, not the 0.7
  the TODO guessed. Both live in `config/constants.py` / `find_similar_books/executor.py`.
- **Generation is a registered node the planner ends a chain with**, not a sink stage
  attached after the runner. Written up in
  [design/execution-pipeline-v1.md](design/execution-pipeline-v1.md) ("Generation node,
  second attempt").
