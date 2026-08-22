# V1 Roadmap

**Updated:** 2026-07-24

## Next move (open decision, 2026-07-24)

The planner is good enough to build on: the 2026-07-24 eval baseline is **157/164**, and
every one of the 7 remaining failures traces to the clarification/rejection node that was
never built — not to routing quality ([eval-strategy.md](eval-strategy.md)). Three
candidates are on the table, and they are not independent:

| Candidate | What it unblocks | What it needs first |
|---|---|---|
| **Real executors** (Phase 3) | Everything — generation has nothing to render and HITL's best pause point has no counts without it | Nothing; mocks are the only thing in the way |
| **Generation node** | The final answer, which currently has no owner | Executor output to render, and the goal-vs-terminal-stage decision |
| **Human-in-the-loop** | The highest-value feature, per the owner | A union fix (small), plus a chosen pause point |

**Recommended order: executors → generation → HITL**, for the owner's own stated reason —
*"I need to get the executors in, because then I know what they need first and I can go
back to the planner."* Generation and HITL both consume executor output; building either
first means designing against mocks and redoing it.

Two things can be done **now**, in parallel, without picking a side:

- Fix the `AnyStrategyRequest` union drift (P1 in [backlog.md](backlog.md)) — 18 of 28
  registered node types cannot be rebuilt from saved JSON, which is precisely what HITL
  resume does.
- Build the clarification/rejection node (Phase 1's last open item) — it is the only thing
  standing between the eval suite and a clean gate, and it is planner-side, so it does not
  collide with executor work.

Design records for the two undecided pieces:
[execution-pipeline-v1.md](design/execution-pipeline-v1.md) (retrieve → filter → analyze →
generate, plus the filter/combine, analyze-book, and generation nodes) and
[human-in-the-loop.md](design/human-in-the-loop.md) (pause points, blockers,
recommendation). The planner's own shape is settled in
[planner-shape.md](design/planner-shape.md).

## V1 philosophy

A small, polished node set that showcases the **planner and orchestration
architecture** — the domain could technically be anything, book recommendation is the
demo. Retrieval + recommendation cores, plus the infrastructure that makes the app feel
complete: clarification/rejection handling, feedback, and clean single-turn conversation
flow. Obvious expansion points are left visible (the UI may hint at future capabilities
without implementing them). No user accounts, so persistent preferences, saved books,
reading history, and personalization are out of scope. On the frontend, **reduce**
features rather than add them.

## Scope decisions (settled 2026-07-17)

Full rationale in [design/node-taxonomy-v1.md](design/node-taxonomy-v1.md):

1. **Clarify-only, single-turn conversation.** Every query stands alone; ambiguous or
   unsupported input always gets a clarification/rejection reply. Multi-turn context is
   the V1.1 flagship.
2. **Retrieval owns filters.** Retrieval nodes (Title, ISBN13, Traits — single-dimension)
   carry all DB filters; `Analyze_Recommend` loses `filters` and becomes the LLM
   ranking/response step. `Analyze_Compare` leaves V1. `Provide_Feedback` gets registered.
3. **The playground extension block stays a manual comment-toggle** (by design); the
   release build ships with it commented out.

## Phases

Dependency order: 1 → 2 → 3 → 3.5; Phase 4 needs only 1–2 (planner-level, so it runs in
parallel with 3); Phase 5 is independent but blocks deploy; Phase 6 wants 3 for the
end-to-end demo path. Phase 3.5 can start before 3 finishes if the pause gate sits before
task execution, but its most useful pause point needs 3.

### Phase 0 — Docs & planning reorganization ✅ (this pass)
Create `docs/`, migrate the TODO files, fix stale READMEs/CLAUDE.md, record review
observations in [eval-strategy.md](eval-strategy.md).

### Phase 1 — Node taxonomy & registry cleanup
- [x] **Retrieval taxonomy (2026-07-17)**: `Retrieve_by_Traits` deleted; `Retrieve_by_Author`
  (promoted from the extended playground schemas) and `Retrieve_by_Genre` (new) added
  alongside the existing `Retrieve_by_Title`/`Retrieve_by_ISBN13` — four single-dimension
  nodes, no `BooksFilter` object on any of them. `filters` stripped from
  `RecommendationStrategy` too. Output contracts added
  (`app/domains/books/schemas/output_schemas.py`). Book-domain registry entries moved to
  `app/domains/books/registry.py`, composed by `app/registry.py`. Mock executors updated
  to match. Full detail: [design/node-taxonomy-v1.md](design/node-taxonomy-v1.md).
- [~] **`Analyze_Compare` — reverted, fate still open.** Removed 2026-07-17, then
  **re-registered 2026-07-18** (commit `9d0e402`, "registered compare for eval test").
  As of 2026-07-24 `CompareStrategy` is back in `BOOK_ANALYZE_CLASSES` and
  `BOOK_NODE_TYPE_TO_CLS`, so the planner offers and accepts it again — but it was never
  re-added to `AnyStrategyRequest` (see the union-drift item in [backlog.md](backlog.md)),
  and the comment above the import in `app/domains/books/registry.py` still describes it
  as parked. The design question that decides this — how compare chains with per-book
  analysis — is in
  [design/node-taxonomy-v1.md](design/node-taxonomy-v1.md#future-considerations) and needs
  the analyze-book node from
  [design/execution-pipeline-v1.md](design/execution-pipeline-v1.md).
- [x] **Register `Provide_Feedback` (2026-07-17)**: added to `PROJECT_NODE_TYPE_TO_CLS`
  (new `app/domains/project/registry.py`, mirroring the books domain), given a
  discriminating docstring (vs. `Retrieve_Project_Info` and vs. re-requesting
  recommendations), and given a mock executor
  (`playground/app_mock/executors/project/feedback.py`) so a plan targeting it actually
  runs. Falls into the catalog's "Other supported actions" tier (not retrieval or
  analyze). Note: this is a *conversational* feedback node, unrelated to the reviewer
  workflow's `PUT /feedback/review` endpoint — different mechanism, same word.
- [ ] **Add the clarification/rejection node** — the last open item, and the single
  highest-leverage planner change left: schema + enum entry + registration + planner
  handling, so refused goals produce a helpful reply instead of a silently smaller plan.
  Cover complexity overload, prompt injection, and degenerate input (the adversarial
  suite's categories) — plus cross-column/quantitative queries ("over 300 pages"), which
  have no node to route to now that `Retrieve_by_Traits` is gone, and contradictory
  queries (should the model infer through a contradiction, or refuse? — refuse, via this
  node). **All 7 failing eval cases as of 2026-07-24 are waiting on it**: `query_suite` 14;
  `adversarial` 311, 314, 315, 336; `stress` 423, 424.
- Extension block untouched — it stays the manual toggle, and it is currently **enabled**
  on this branch.

**Exit:** with the extension block commented out, `python -m app.registry` prints
exactly the V1 catalog from the taxonomy doc. (Retrieval side and `Provide_Feedback`
already match; the clarification node and Compare's final status are pending.)

### Phase 2 — Prompt & docstring catalog improvements ✅ (2026-07-18)
- [x] **Generic prompts (2026-07-18)**: both `0_initial_system.txt` (parse-intent) and
  `2_strategy_classification.txt` (strategy-classification) rewritten into the same
  generic markdown shape (`Role/Objective/Trust Boundaries/Rules/Guidelines/Output/Catalog`).
  Zero book-specific wording in either; the book-specific `{book_constraints}`/`{book_guides}`
  placeholders and their call-site injection were dropped along with the old free-text
  Examples blocks.
- [x] **Example queries + Args/Returns signatures on every node docstring**: all V1 node
  schemas (`app/domains/{books,project,users}/schemas/request_schemas.py`) follow
  `Purpose/Args/Returns/Use when/Do not use/Constraints/Example queries`. Compound-intent
  coverage (secondary goals like feedback/project info alongside a book request, so they
  stop getting dropped) lives as eval cases in `evals/suites/query_suite.json`
  (ids 37/41/45/47/50) — actual pass/fail verification is Phase 4's job.
- [x] **Few-shot examples moved into schemas**: worked examples for both pipeline-stage
  tool calls (`GoalParseRequest`, `StrategyRequest`) now live as
  `model_config` JSON-schema `examples` on the pydantic models themselves
  (`parse_intent.py`, `strategy_classification.py`) instead of free-text prompt blocks —
  this way they survive into the actual OpenAI tool schema sent to the LLM.

**Exit:** catalog renders examples + signatures; prompt contains nothing book-specific.

### Phase 3 — Execution end-to-end ← **recommended next**
- Real executors for the V1 nodes: retrievals via `db/stores/book_store.py`,
  `Analyze_Similar_Books` as the semantic search step, info nodes, feedback node;
  the clarification node responds directly. *(2026-08-22: the ranking and the
  written reply split out of the similarity node into a picker node that is not
  written yet — so nothing answers a book turn in prose today.)*
- Repoint `EXECUTORS_CLS_MAPPING` from the mocks to the real executors
  (`app/registry.py` — the NOTE there marks this).
- Re-enable `TaskRunnerWorkflow` in `Orchestrator.run`
  (`app/orchestration/orchestrator.py` — currently commented out).
- **Decide the pipeline shape before writing executors**, since it changes what a
  retrieval executor returns: the proposal is retrieval → counts/metadata only,
  filter/combine via CTE, analyze executes, generation renders. Full record and open
  questions in [design/execution-pipeline-v1.md](design/execution-pipeline-v1.md).
- New nodes that fall out of that shape, none of which exist yet: **filter/combine**,
  **analyze-book** (also unblocks `Analyze_Compare`), **generation**.

**Exit:** a title query returns real books from the database over SSE, end to end.

### Phase 3.5 — Human-in-the-loop (pause / persist / resume)
Promoted out of the deferred list 2026-07-24 — the owner rates it the highest-ROI feature
left. Needs a pause event over SSE, trace persistence, a resume endpoint, and workflow
rehydration. Pause-point candidates, blockers (union drift, the checkpoint gap, private
workflow state), and the recommendation to gate *before* `TaskRunnerWorkflow` starts are
all in [design/human-in-the-loop.md](design/human-in-the-loop.md).

**Exit:** one run pauses, survives a page reload, and continues from the user's answer.

### Phase 4 — Eval relabel & golden tests
- [x] **Relabel done (2026-07-24)**: every suite case's `expected_nodes` now records the
  `v1_baseline` campaign's actual accepted goals rather than a pre-taxonomy wish, with
  reviewer comments overriding the run where the reviewer contested the plan itself.
  56 of 164 cases changed; the gate moved 104/164 → **157/164**.
- [ ] Add clarification-expected cases once that node exists — the 7 current failures are
  already exactly those cases, so they double as its acceptance test.
- [ ] Extended suite runs only when the extension block is enabled.
- [ ] Set pass thresholds now that a real baseline exists; `make suite-goals` becomes the
  release gate.

**Exit:** one command reports pass/fail against the V1 node set.

### Phase 5 — Security hardening (blocks deploy)
From the 2026-07-12 security review (full detail in [backlog.md](backlog.md)):
- Auth/admin gating on `GET /chat_runs` (currently exposes every session's full history).
- Session-ownership verification on feedback read/write.
- Tighten CORS `allow_methods` (`app/main.py`).
- Replace `uuid_8()` with a longer id; add `FeedbackIn.message` max_length.

**Exit:** none of the P1 security items remain open.

### Phase 6 — UI polish & future hints
- Fix the session-creation race and the unreachable 3-minute timeout.
- Review-page alignment; move feedback controls per frontend polish notes.
- Surface a capability/tool catalog or "coming soon" hints for deferred features —
  the UI hints at V2 without implementing it.

**Exit:** demo flow is smooth; deferred features are visible but honest.

### Phase 7 — Docs upkeep & release
Re-verify README/CLAUDE.md/docs against implemented reality, comment out the extension
block, walk the release checklist below.

## Release checklist ("Definition of Done" — what must be true to call V1 shipped)

- [ ] Every V1 node plans **and executes** end-to-end with real data streamed over SSE.
- [ ] Ambiguous/unsupported input always gets a clarification or rejection reply.
- [ ] Extension block commented out in the release build.
- [ ] Relabeled suites pass their thresholds via `make suite-goals`.
- [ ] Phase 5 security blockers closed.
- [ ] README, CLAUDE.md, and docs/ accurate against the code.
- [ ] Feedback review flow works with ownership checks.

## Deferred (V1.1 and beyond)

| Feature | Notes |
|---|---|
| **Multi-turn conversation context** | V1.1 flagship. `chat_runs` already records turns; needs history loading + prompt changes + summary (`PlannerOutput.to_summary` is a stub) |
| `Analyze_Compare` | Currently re-registered for eval testing; final fate waits on the analyze-book node ([design/execution-pipeline-v1.md](design/execution-pipeline-v1.md)) |
| Extension-node graduation | Promote earned extended nodes via the standard add-a-node path |
| User accounts & personalization | Preferences, saved books, reading history — all need a user DB |
| Human-in-the-loop re-rank | Recommendation node is the natural spot — a *later* application of Phase 3.5's machinery, not its first cut |
| Checkpoint/resume + incremental step recording | Needs workflow rework (backlog: Workflow framework); blocker 2 for Phase 3.5 |
| Server-side stop | `stopChatStream` exists client-side but has no backend endpoint |
| Book-clamped recommendations | "Do you have Dune? — yes, and you'll like these" |
| Reading lists / ratings / library actions | Live only as extension schemas today |
