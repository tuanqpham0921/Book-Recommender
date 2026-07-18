# V1 Roadmap

**Updated:** 2026-07-17

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

Dependency order: 1 → 2 → 3; Phase 4 needs only 1–2 (planner-level, so it runs in
parallel with 3); Phase 5 is independent but blocks deploy; Phase 6 wants 3 for the
end-to-end demo path.

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
- [x] **Remove `Analyze_Compare` (2026-07-17)**: pulled from `BOOK_ANALYZE_CLASSES`,
  `BOOK_NODE_TYPE_TO_CLS`, `AnyStrategyRequest`, and the mock executor mapping.
  `CompareStrategy`/`CompareBooksExecutor` stay defined and directly importable
  (genuinely parked, not deleted) — the planner just never offers or accepts them
  (`parse_intent.py` gates on `NODE_TYPE_TO_CLS` membership).
- [x] **Register `Provide_Feedback` (2026-07-17)**: added to `PROJECT_NODE_TYPE_TO_CLS`
  (new `app/domains/project/registry.py`, mirroring the books domain), given a
  discriminating docstring (vs. `Retrieve_Project_Info` and vs. re-requesting
  recommendations), and given a mock executor
  (`playground/app_mock/executors/project/feedback.py`) so a plan targeting it actually
  runs. Falls into the catalog's "Other supported actions" tier (not retrieval or
  analyze). Note: this is a *conversational* feedback node, unrelated to the reviewer
  workflow's `PUT /feedback/review` endpoint — different mechanism, same word.
- [ ] Add the clarification/rejection node: schema + enum entry + registration + planner
  handling, so refused goals produce a helpful reply instead of a silently smaller plan.
  Cover complexity overload, prompt injection, and degenerate input (the adversarial
  suite's categories) — plus cross-column/quantitative queries ("over 300 pages"), which
  have no node to route to now that `Retrieve_by_Traits` is gone.
- Extension block untouched — it stays the manual toggle.

**Exit:** with the extension block commented out, `python -m app.registry` prints
exactly the V1 catalog from the taxonomy doc. (Retrieval side already matches; Compare
removal and Provide_Feedback registration still pending.)

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
  tool calls (`InitialParseRequest`, `StrategyRequest`) now live as
  `model_config` JSON-schema `examples` on the pydantic models themselves
  (`parse_intent.py`, `strategy_classification.py`) instead of free-text prompt blocks —
  this way they survive into the actual OpenAI tool schema sent to the LLM.

**Exit:** catalog renders examples + signatures; prompt contains nothing book-specific.

### Phase 3 — Execution end-to-end
- Real executors for the V1 nodes: retrievals via `db/stores/book_store.py`,
  `Analyze_Recommend` as the LLM response/ranking step, info nodes, feedback node;
  the clarification node responds directly.
- Repoint `EXECUTORS_CLS_MAPPING` from the mocks to the real executors
  (`app/registry.py` — the NOTE there marks this).
- Re-enable `TaskRunnerWorkflow` in `Orchestrator.run`
  (`app/orchestration/orchestrator.py` — currently commented out).

**Exit:** a title query returns real books from the database over SSE, end to end.

### Phase 4 — Eval relabel & golden tests
- Relabel every suite case's `expected_nodes` to the V1 taxonomy; add
  clarification-expected cases. Details in [eval-strategy.md](eval-strategy.md).
- Extended suite runs only when the extension block is enabled.
- Set pass thresholds after the first post-Phase-1 run; `make suite-eval` becomes the
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
- [ ] Relabeled suites pass their thresholds via `make suite-eval`.
- [ ] Phase 5 security blockers closed.
- [ ] README, CLAUDE.md, and docs/ accurate against the code.
- [ ] Feedback review flow works with ownership checks.

## Deferred (V1.1 and beyond)

| Feature | Notes |
|---|---|
| **Multi-turn conversation context** | V1.1 flagship. `chat_runs` already records turns; needs history loading + prompt changes + summary (`PlannerOutput.to_summary` is a stub) |
| `Analyze_Compare` | Returns after single-book analysis exists |
| Extension-node graduation | Promote earned extended nodes via the standard add-a-node path |
| User accounts & personalization | Preferences, saved books, reading history — all need a user DB |
| Human-in-the-loop re-rank | Recommendation node is the natural spot |
| Checkpoint/resume + incremental step recording | Needs workflow rework (backlog: Workflow framework) |
| Server-side stop | `stopChatStream` exists client-side but has no backend endpoint |
| Book-clamped recommendations | "Do you have Dune? — yes, and you'll like these" |
| Reading lists / ratings / library actions | Live only as extension schemas today |
