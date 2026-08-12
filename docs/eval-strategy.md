# Evaluation Strategy

**Updated:** 2026-07-24 · Operational how-to lives in
[../backend/evals/README.md](../backend/evals/README.md); this doc is the strategy:
what the suites are for, what the latest campaign found, and how the framework grows
with the app.

## The mechanism (this *is* the golden-test system)

The suite JSONs in `backend/evals/suites/` are versioned inputs with per-case
`expected_nodes`. `run_suites.py` fires each query at a running backend and records one
`test_runs` row per query (chat_id FK → `chat_runs` + suite name + case id).
`report_system_goals.py` (`make suite-goals`) joins `test_runs ⋈ chat_runs` and
multiset-diffs the planner's accepted goal node types against `expected_nodes` →
matched/missing/extra per case. It reports correctness only — tokens, dollars and
latency live in the separate cost report (`make suite-report`), so a gate diff never
churns on numbers that move every run.

Two properties make this the right foundation:

- **It's planner-level.** It grades the *plan* (accepted goals), not execution — so it
  works today with executors mocked, and it keeps working unchanged when TaskRunner
  goes live. Execution-level grading can be layered on later without redesign.
- **It grows by adding JSON cases**, not by changing the harness. New node → new cases
  with `expected_nodes`; that's the whole extension story.

The intended growth loop (matches the owner's workflow): finalize nodes → build eval
cases around them → set thresholds (golden tests) → expand nodes and coverage together.

## Suite inventory

| Suite | Cases | Purpose |
|---|---|---|
| `query_suite.json` (base) | 70 | Core node set, easy→hard, single lookups to 7-node cross-domain chains |
| `query_suite_adversarial.json` | 54 | Rejection behavior: prompt injection, impossible facts, degenerate input, sounds-supported-but-unimplemented (17 cases intentionally expect no nodes) |
| `query_suite_extended.json` | 48 | Node-*scaling* test (~26 node types); heavy on near-miss discrimination. **Dormant since 2026-08-10** — the registry extension block was removed with the `Registry` refactor; reviving it means giving the playground schemas real `NodeSpec`s and passing them to `Registry` alongside `SPECS` |
| `query_suite_stress.json` | 9 | Buffer/overflow past `MAX_SYSTEM_GOALS`/`MAX_STRATEGIES`, confusing multi-hop chains |

`make query-suite-all` fires all four concurrently — that doubles as the multi-user
concurrency test.

## Latest campaign (2026-07-16): what the data says

Reports: `backend/evals/results/newest/eval_20260716_002307.md` and `stats_.md`.

**Overall 101/159 matched** — base 33/50, adversarial 29/52, extended 38/48, stress 1/9.
Outcome-wise: 155/159 ran ok, **0 runtime errors**, 987,867 tokens total (avg 6,213),
avg 9.38s (stress avg 23.77s; worst 51.8s).

Recurring failure patterns, in priority order:

1. **Traits ↔ Recommend blur** (base 11, 25, 30, 39; also 15/122/356 vs
   `Retrieve_Popular`) — structural; fixed by the taxonomy decision
   ([design/node-taxonomy-v1.md](design/node-taxonomy-v1.md)).
2. **Compound messages drop secondary intents** — `Provide_Feedback`,
   `Retrieve_Project_Info`, `Retrieve_User_Info` go missing on cases 9, 10, 29, 41,
   145, 148. Partly the unregistered feedback node, partly a parse prompt with no
   compound-intent examples (roadmap Phase 2).
3. **Stress plans spray extra nodes** — case 411 produced 10 extra
   `Retrieve_by_Title`; 412/421/422 sprayed unrelated extended nodes. Over-budget
   requests need a clean rejection instead of a partial/exploded plan (Phase 1's
   clarification node).
4. **`Retrieve_by_Author` over-triggers** whenever an author appears in the query
   (330, 331, 333, 353, 355) — extension-suite discrimination problem; docstring
   examples are the lever. The 2026-07-21 author split
   ([design/node-taxonomy-v1.md](design/node-taxonomy-v1.md)) adds a second axis to
   this: a two-name query now has to pick between N `Retrieve_by_Author` nodes and one
   `Retrieve_by_CoAuthors`. Base cases 53/54 are that pair — same shape, opposite
   expected plan — and 55 covers the yes/no phrasing.

## Baseline established (2026-07-24)

`expected_nodes` is now a **recorded baseline, not a wish list**. Every case's expectation
was rewritten from what the `v1_baseline` campaign's planner actually accepted
(`backend/evals/results/v1_baseline/`), with two guards: never adopt a run that failed,
and never adopt a run where the reviewer contested the *plan* — those keep the reviewer's
answer or the prior expectation instead. 56 of 164 cases changed; the gate moved
**104/164 → 157/164**.

The single biggest source of the old failures was structural: 29 cases expected
`Retrieve_by_Traits`, a node deleted by the taxonomy decision and absent from the live
registry, so they could never pass at any planner quality.

Read a red as "behavior changed since the baseline" — either a regression, or an
improvement that should be re-baselined deliberately.

### Known-failing by design (7 cases)

`query_suite` 14 · `adversarial` 311, 314, 315, 336 · `stress` 423, 424. All seven need
the clarification/rejection node ([roadmap.md](roadmap.md) Phase 1) — over-budget requests,
contradictory queries, and duplicate-node plans that should collapse into one refusal.
They are the acceptance test for that node, not noise; leave them red until it lands.

### Design-intent cases added 2026-07-28

Written from the taxonomy, not from a recorded run, so they are unbaselined — read a red
here as "not implemented yet", not as a regression:

- `query_suite` **66, 67** — `Retrieve_Random`'s promotion to V1 core: the bare recommend
  and the bounded surprise ([design/node-taxonomy-v1.md](design/node-taxonomy-v1.md)).
- `query_suite` **68** — author-anchored recommend, the last corner of the recommend
  triangle (title / genre / author). Pairs with 66: same phrasing, one anchor apart.
- `query_suite` **69** — compare scoped to one attribute, recommend pivoting on another.
  Same node types as case 36 by design; it exists for the argument-level split, which the
  goals report cannot see.
- `query_suite` **70** — `Analyze_Compare` over an `Analyze_Recommend` result. **Expected
  red until a decision lands**: Compare's docstring says "depends_on: at least 2 nodes",
  but the arity a comparison actually needs is two *books*, and here one node carries
  both. Also the first case to need a `limit` on `Analyze_Recommend`, which has no such
  field — the "2" is unexpressible today.
- `adversarial` **358, 359** — "recommend authors like X". No node returns authors, but
  the ask is answerable in substance as books; both expect the books plan, and both are
  invisible to the node-type diff (identical types to 68). The argument for
  argument/answer-level checking, alongside cases 57 and 60.

## Remaining relabel work (roadmap Phase 4)

- Add **clarification-expected cases**: ambiguous queries, prior-turn references
  ("that one from earlier"), over-budget requests — expecting the new
  clarification/rejection node.
- Add the owner's pending cases: bad words, and the fictional "Chronicles of Zephyrian
  Doombringer" series + everything by its author (nonexistent-entity behavior).
- Gate the extended suite: run only when the extension block is enabled; don't count it
  toward the release gate.
- Improve case labeling for automatic testing (descriptions/notes surfaced in reports;
  numeric chat ids already exist).

**Thresholds:** now settable — the 2026-07-24 rebaseline removed the structural pollution
that made the old numbers meaningless. `make suite-goals` becomes the release gate: base
+ adversarial must clear their thresholds for V1 to ship.

## Observations from the 2026-07-17 review

Recorded here (not in the feedback table — decided with the owner) in the same shape as
review-page feedback — **category / praise-or-issue / message** — so they double as
examples of the review workflow:

- **Planner / issue** — base cases 11, 25, 30, 39 (expected `Analyze_Recommend`, got
  `Retrieve_by_Traits`): the planner isn't wrong so much as the schemas are — both nodes
  carry filters, so either is a defensible parse. Structural fix scheduled (taxonomy
  decision); prompt tuning alone would have plateaued here.
- **Planner / issue** — stress case 411 (17× Save_To_Reading_List request → 10 extra
  `Retrieve_by_Title`): over-budget input currently degrades into a sprayed plan. A
  visible "this request is too large, here's what I can do" rejection would showcase
  the planner better than a partial plan — good V1 story, not just a fix.
- **Planner / issue** — cases 9, 10, 29, 41 (compound messages): secondary intents
  (feedback, project info) get dropped. Registering `Provide_Feedback` removes one
  cause; catalog examples with compound queries are the other half.
- **Time / issue** — stress avg 23.77s vs base 9.01s (case 402: 51.8s; case 424: 11,817
  tokens): latency scales with plan size. Fine for a chatbot demo, but worth surfacing
  progress ("running step 3/7") in the UI before V1 rather than optimizing now.
- **Content / issue** — extended case 136 (`chat_run_chat_8a78ec8a`, Russian-classics
  reading plan, run failed, 29s): owner's footnote suspects the unclear extended
  ReadingPlan tool description — concrete evidence for Phase 2's docstring/examples
  work, and a good regression case to keep.
- **Planner / praise** — 155/159 ran ok with **zero runtime errors** across four suites
  fired concurrently, including prompt-injection and unicode-stress cases. The
  OperationResult/Workflow envelope is doing exactly what it was designed for; the
  failures that remain are routing quality, not stability.
