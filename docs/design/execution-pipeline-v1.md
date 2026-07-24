# Execution pipeline: retrieve → filter → analyze → generate (design record)

**Date:** 2026-07-24 · **Status:** partly implemented — the combine tier's *schemas* are
registered; no executors, no counts-only retrieval, no generation node.

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

### Filter / combine nodes — **registered 2026-07-24**

Built as **three** nodes rather than the one this record originally sketched, because
"combine" turned out to be two different operations that must not be confused:

| node type | class | operation | `depends_on` | carries `filters` |
|---|---|---|---|---|
| `Combine_Union` | `UnionRetrieval` | OR — pool inputs, dedup | ≥ 2 | no |
| `Combine_Intersect` | `IntersectRetrievals` | AND — keep books in *every* input | ≥ 2 | no |
| `Filter_Retrieval` | `FilterRetrieval` | narrow by metadata bounds | ≥ 1 | **yes, required** |

All three live in `app/domains/books/schemas/request_schemas.py`, sit in their own
`CATALOG_TIERS` section, and consume prior task output only — none of them queries the
database.

The open question above ("one node with a filter object, or a family of single-dimension
filter nodes?") resolved to **one node with a filter object**, but a deliberately narrow
one. `Filter_Retrieval` carries `BookMetadataFilter`
(`db/schema/filter_schemas.py`) — pages, year, rating, ratings count, is_children — which
is `BooksFilter` minus every field that could serve as a search subject. No authors, no
categories, and critically **no `keywords` free-text field**: that field is what blurred
the old `Retrieve_by_Traits` into `Analyze_Recommend`, and leaving it out is what keeps
this node a narrowing operator instead of a second recommender.

**One operation per node.** The set operators carry no filters — an earlier cut gave
`Combine_Union` and `Combine_Intersect` an optional `BookMetadataFilter` applied after the
set operation, and that was removed. Two reasons: every constraint then had two legal
homes (inline on the combine node, or a downstream `Filter_Retrieval`), which is precisely
the kind of "either parse is defensible" ambiguity the taxonomy decision was meant to
eliminate; and it made the combine nodes' catalog entries carry filter documentation that
`Filter_Retrieval` already owns. The cost is longer plans — "fantasy books by Sanderson
over 400 pages" is now four nodes — traded for one unambiguous home per operation.

`depends_on` moved from `AnalyzeBaseRequest` up to a new `DependentRequest` base, since
these nodes consume task output without analyzing it. The planner's dependency remapping
and topological sort gate on `DependentRequest`.

**Known limitation, unresolved:** `Combine_Intersect` intersects *materialized* result sets,
and retrieval today returns a `limit`-capped list (default 3). Intersecting two capped
lists is usually empty — "fantasy books by Sanderson" would intersect a 3-book author page
against a 3-book genre page and return nothing. The node is semantically right and
operationally wrong until retrieval returns counts/queries rather than rows, which is
exactly the counts-only change described above. Whoever writes the intersect executor has
to push the predicate into the upstream query rather than intersect two result lists.

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

- ~~One filter node with a filter object, or several single-dimension filter nodes?~~
  Resolved 2026-07-24 — one node, one narrow filter object; see above.
- **Do the base suite's multi-anchor expectations still hold?** Cases 56, 57 and 59 were
  written on 2026-07-24 expecting a *single* `Retrieve_by_Author` with the genre silently
  dropped, because no combine operator existed. `Combine_Intersect` now gives that shape a
  correct plan (`Retrieve_by_Author` + `Retrieve_by_Genre` + `Combine_Intersect`), so those
  expectations describe the old world. They need re-deciding, not just re-running.
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
