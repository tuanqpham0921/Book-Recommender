# Improvement Recommendations — from the `test_2ca761aa` planner review

Ordered by (impact on user-visible correctness) / (effort). Items 1–3 are the
ones I'd do before wiring up TaskRunner; the rest can ride along with the
node-taxonomy re-arch you're already planning.

---

## 1. Goal-coverage validation in `StrategyClassificationWorkflow` (high impact, small)

**Problem:** an accepted goal with no covering task vanishes silently
(run 37), and refusal cascades can silently halve a request (run 36). You
couldn't tell from the logs whether the LLM or your filter dropped it.

**Fix:** at the end of `_create_dag`, diff
`{goal.id for goal in system_goals}` against
`union(task.target_goal for task in output.accepted)` and record the
difference on the output (e.g. `uncovered_goals: list[SystemGoal]`), with a
`logger.warning`. Then:

- v1 (cheap): surface it — a note in the mermaid/user response: "I couldn't
  plan a step for: *find books about the technologies used*".
- v1.5 (one extra call, only on failure): re-ask classification once, naming
  the uncovered goals. This is the "repair pass" version of your step-by-step
  idea — iterative behavior only when the upfront plan is actually broken.

This also gives you the eval metric you were hunting for manually:
`% runs with uncovered goals` straight from the recorder.

## 2. Fix exclusion semantics end-to-end (high impact, medium)

Two halves (see report F1):

- **Store:** implement `filters.exclusion` in `apply_book_filters` —
  `NOT ilike` for excluded authors/categories/titles. Until then,
  `ExclusionBookFilter` is decorative and run 39's plan executes as the
  opposite of the request.
- **Planner prompt:** add one rule + example to
  `2_strategy_classification.txt`: *"values in `exclusion` must not appear in
  `authors` / `categories` / `keywords`"*. Optionally enforce in
  `BooksFilter.model_post_init` (strip overlap, keep exclusion side, add a
  detail note) so it's guaranteed regardless of the LLM.

**Test to add** (`tests/unit/db/stores/test_utils.py`): compile
`build_filtered_search` with an exclusion filter and assert the SQL contains
the NOT clause; a second test asserting overlap-stripping if you do the
post-init route.

## 3. Enumerate fields in node docstrings (high impact, tiny)

Runs 10 and 29 misrouted in-scope requests because the parse LLM never sees
what `Retrieve_User_Info` / `Retrieve_Project_Info` can actually fetch.
The docstrings are already the tool descriptions — extend them:

- `UserInfoRequest`: "...fields: name, age, bio, token_usage, saved_memory,
  previous/current conversation."
- `ProjectInfoRequest`: "...fields: name, description, tech stack, project
  URL, GitHub repo name/URL."

**Test to update:** `test_registry.py` already checks docstring substance; if
you want it pinned harder, assert the catalog mentions "token_usage" and
"github" (case-insensitive) so a future docstring trim can't regress routing.

## 4. Make unimplemented capabilities fail one way (medium, small)

`Provide_Feedback` is in `NodeTypeEnum` (so the parse schema advertises it)
but not in `NODE_TYPE_TO_CLS` (so it's refused when chosen) — and when the
LLM *doesn't* choose it, it shoehorns feedback intent into
`Retrieve_Developer_Info` (run 50). Pick one:

- **Register it** (the `FeedbackRequest` class already exists) and stub the
  executor with a "coming soon" response — you get roadmap signal for free; or
- **Constrain the schema**: build `SystemGoal.target_node_type`'s enum from
  `NODE_TYPE_TO_CLS.keys()` instead of the full `NodeTypeEnum`, so the LLM
  can't emit unsupported types at all, and add a catalog line telling it to
  put unsupported actions in `out_of_scope`.

I'd do the first — your run-41/50 data shows users genuinely try to send
feedback mid-chat.

## 5. Tighten `small_talk` / `out_of_scope` contract (medium, tiny)

Prompt + field-description change only: small_talk is *greetings and
pleasantries*, never a request; anything actionable must become a goal or
out_of_scope. Add run 49's message as a counter-example in the prompt
("look up my conversations and recommend" → goals, NOT small_talk).
Run 09 stays the positive example.

## 6. OR keywords within one intent (medium, small)

`apply_book_filters` ANDs each keyword's condition; run 06's five spooky
keywords require a book to match all five. Wrap the keyword conditions in a
single `or_(...)` (mirroring how authors/categories already work), or route
multi-keyword semantic intent to the embedding search instead.

**Test to add:** filter with `keywords=["a", "b"]` → compiled SQL contains
`OR` between the keyword conditions, not `AND`.

## 7. Stop echoing corpus bounds as filters (low, tiny)

Prompt line in `2_strategy_classification.txt`: "BookConstraints describe the
corpus; emit a bound only when the user's request implies it. Leave fields
null otherwise." Cleans up plan readability (runs 06/13/25/30) and makes
`filters` diffs meaningful in future evals.

## 8. Dependency-relevance check (low, small)

Run 45: recommend depended on an unrelated project-info task, serializing
independent work. Cheap heuristic in `_create_dag`: warn (don't refuse) when
an Analyze task depends on a task with which it shares no `target_goal`.
Keep it a warning — run 47 shows cross-goal deps can be intentional.

## 9. Deferred / "pending" args — design note for the re-arch (your idea, endorsed)

Runs 26 ("shorter than Dune") and 50 ("exclude authors I've read") both need
argument values that only exist after a dependency runs. Today the LLM
substitutes BookGuides absolutes at plan time. Your "pending instead of
straight parsing" note is the right shape; the minimal version:

```python
class PendingArg(BaseModel):
    from_task: str        # dependency task id
    expression: str       # e.g. "page_count * 0.8", "authors"
```

Fields typed `int | PendingArg` etc. The executor resolves them when the
dependency completes. You don't need this for v1 (you said so yourself), but
designing node schemas now so scalars can later become `X | PendingArg`
keeps the door open.

## 10. Node taxonomy for the re-arch (consolidating your notes + my findings)

Your retrieval-first instinct matches the evidence. Concretely:

- **Remove `filters` from `RecommendationStrategy`** — it's the single source
  of the traits/recommend blur (run 03 duplicated identical filters into both
  nodes). Recommend consumes candidates from retrieval deps + semantic_input.
- **Keep `Analyze_Compare` separate** (your fb_550ff751 was right) — it never
  blurred with anything in 50 runs; the only compare failures were dependency
  arity, not identity.
- **Add `Analyze_Book` (single-book text generation)** when you get to it —
  runs 01/05 show retrieval-only is acceptable for v1 since cards carry
  descriptions.
- **Clarification node** (runs 12, 30 — your fb_4117ce3f, fb_076c0f92): defer;
  both runs produced reasonable guesses, and clarification needs UX work
  (mid-plan user input) that fights the current one-shot SSE flow.

---

## Test plan summary

Done in this review:

- `app/registry.py` — fixed retrieval classes being listed twice in every
  parse prompt (`listed` now includes `RETRIEVAL_CLASSES`).
- `tests/unit/app/domains/test_registry.py::test_catalog_lists_every_node_type_exactly_once`
  — pins the fix. (4/4 registry tests pass.)

Recommended next (in priority order, matching items above):

1. `test_strategy_classification.py`: **goal coverage** — feed
   `_create_dag` a parse_result whose strategies cover only 1 of 2 goals;
   assert the uncovered goal is recorded/logged (write after implementing #1;
   currently it would fail).
2. `test_utils.py` (db/stores): **exclusion applied** + **keyword OR** SQL
   compilation tests (items #2, #6).
3. `test_parse_intent.py`: **small_talk contract** — schema-level test that
   `process_parse_result` treats a goals+small_talk-overlap payload sanely is
   not really unit-testable (it's prompt behavior); instead add these cases
   to your eval query suite (`tests/scripts/run_query_suites.py`):
   "How many tokens have I used?", "What's the GitHub repo?",
   "similar to ISBN <x>", "compare A and B then recommend the darker one" —
   the four misroute patterns from this session, so the next eval run
   measures them automatically.
