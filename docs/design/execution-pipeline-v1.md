# Execution pipeline: retrieve → filter → analyze → generate (design record)

**Date:** 2026-07-24 · **Status:** proposed — nothing implemented yet

Graduated from `backend/TODO.md`. This is the shape execution is expected to take once
[roadmap Phase 3](../roadmap.md) starts, and it defines three nodes that do not exist
today. The node set as currently registered is in [node-taxonomy-v1.md](node-taxonomy-v1.md);
the pause points this shape creates are in [human-in-the-loop.md](human-in-the-loop.md).

## Where execution stands today

- `EXECUTORS_CLS_MAPPING` in `backend/app/registry.py` still points at the **mock**
  executors in `playground/app_mock/`.
- `TaskRunnerWorkflow` is implemented but **commented out** in `Orchestrator.run`
  (`app/orchestration/orchestrator.py`), so today's request flow stops after the planner
  renders its diagram.
- Nothing turns executor output into prose. The final assistant message has no owner.

So the pipeline below is being designed on a clean slate — the argument this record makes
is about *what shape to build*, before any of it is written.

## The proposed shape

Four tiers, each with one job:

| Tier | Job | Returns |
|---|---|---|
| **Retrieval** | Resolve one dimension; **count and metadata only** | How many books match, plus the query to reach them — not the rows |
| **Filter / combine** *(new)* | Apply cross-cutting constraints by composing the upstream queries into a CTE | A narrowed query, still not materialized |
| **Analyze** | Execute the composed query with its own step; interpret the result | Structured output data |
| **Generation** *(new)* | Turn the collected outputs into the user-facing answer | Prose / frontend sections |

The load-bearing idea is that **retrieval does not materialize rows**. `Retrieve_by_Genre`
for horror runs a `COUNT` and hands the query downstream; a `WITH` clause (CTE) composes
it with whatever comes next; the analyze step is the first thing that actually executes
for rows.

### Why this shape

1. **It creates a natural human-in-the-loop moment.** Counts are known before any large
   result set is built, so the system can ask *"that's 4,000 horror books — narrow it
   down?"* or *"nothing matched — did you mean…?"* at **each step**, not only at the end.
   This is the concrete reason the pipeline is worth designing before executors are
   written; see [human-in-the-loop.md](human-in-the-loop.md).
2. **It gives cross-column queries somewhere to go.** The node taxonomy deliberately made
   every retrieval node single-dimension and single-valued, which left *"sci-fi books over
   300 pages"* with no node to route to. A filter/combine node serves that shape without
   adding a combinatorial pile of retrieval nodes, and without putting a `BooksFilter`
   object back on a planner-facing schema — the thing the taxonomy decision explicitly
   removed.
3. **It matches the columns already deferred.** `published_year`, `average_rating`,
   `num_pages`, `ratings_count`, `is_children`, and `categories` are real `BookModel`
   columns that live in `db/schema/filter_schemas.py`'s `BooksFilter` for store queries but
   are not exposed to the planner. The filter node is where they become reachable, in one
   node instead of six.

**Accepted cost:** many more database round trips per request (one per retrieval count,
plus the analyze execution). Fine for V1 — the demo is the planner, not throughput.

## The new nodes

### Filter / combine node

Only composes and applies constraints; it never does lookup. Inputs are upstream task ids
plus the constraints that have no dimension node of their own. Open: whether it is one
node with a filter object, or a small family (`Filter_by_Pages`, `Filter_by_Year`, …) that
keeps the single-dimension rule intact at the cost of catalog size.

### Analyze-book node

Needed for question-answering about a specific book ("what is Dune about?", "is it
appropriate for a 12-year-old?") — retrieval alone answers nothing. It also unblocks the
open `Analyze_Compare` question in
[node-taxonomy-v1.md](node-taxonomy-v1.md#future-considerations): compare was parked
pending exactly this node, and the "retrieve ×2 → analyze ×2 → compare" plan shape cannot
be evaluated until per-book analysis exists.

### Generation node

Owns the final answer. Sketched fields: the **portion of the query** it is answering
(`str`), plus the upstream outputs it renders. Every retrieval and analyze node just
returns output data; generation is what the user reads, and it maps to the sections the
frontend already renders.

**Open question, and the main reason this is not yet decided:** is generation a *goal*
the planner emits (visible in the diagram, one per answer section, dependencies like any
other node), or a fixed terminal stage the orchestrator always appends? As a goal it is
eval-checkable and can fan out per section; as a fixed stage it never gets misrouted and
costs no catalog tokens. If it is a goal, how goals link to sections needs its own answer.

## Open questions

- One filter node with a filter object, or several single-dimension filter nodes?
- Is generation a planner goal or a fixed terminal stage? If a goal — one per answer
  section, or one per request?
- Does the CTE composition live in the executors or in `db/stores/book_store.py`? The
  store currently exposes `search_by_filters` / `search_by_book_filter` / `search_by_title`
  / `search_by_embedding`, all of which materialize rows.
- Does retrieval-returns-counts change the retrieval **output contracts** in
  `app/domains/books/schemas/output_schemas.py` (today they carry `BookSummary` lists)?
- How does a mock executor represent "a query I have not run yet" so this can be tested
  before real executors exist?

## Before building this

The planner side is settled enough to proceed (2026-07-24 baseline: 157/164, all reds
attributable to the unbuilt clarification node). What is *not* settled is whether to build
executors, generation, or human-in-the-loop first — that sequencing decision, and its
reasoning, is recorded in [../roadmap.md](../roadmap.md) under "Next move".
