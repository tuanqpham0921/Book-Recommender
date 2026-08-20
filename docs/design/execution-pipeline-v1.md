# Execution pipeline: retrieve → filter → analyze → generate (design record)

**Date:** 2026-07-24 · **Status:** counts-only retrieval and CTE composition are **built**
(2026-08-04) on `minimal_end_to_end_v1`, for the nodes registered there; the combine
tier's *schemas* exist with no executors, and there is no generation node.

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

Built as **two** nodes rather than the one this record originally sketched, because
"combine" turned out to be two different operations that must not be confused:

| node type | class | operation | `depends_on` | carries `filters` |
|---|---|---|---|---|
| `Combine_Union` | `UnionRetrieval` | OR — pool books from *any* input (dedup by ISBN13) | ≥ 2 | no |
| `Combine_Intersect` | `IntersectRetrievals` | AND — keep books in *every* input | ≥ 2 | no |
| `Filter_Retrieval` | `FilterRetrieval` | narrow by metadata bounds | ≥ 1 | **yes, required** |

All three sit in their own catalog section (`NodeTier.COMBINE`) and consume prior task
output only — none of them runs a lookup of its own.

**`Filter_Retrieval` is built and registered (2026-08-17).** It is a vertical slice like
every other node now — `app/domains/books/filter_books/`, on the single-call
`find_by_title/` template — rather than a schema in a shared `request_schemas.py`; the two
`Combine_*` nodes are still parked. One line of the original sketch did not survive
counts-first: "neither queries the database" was written when a filter would delete from a
materialized list. The executor instead pools its anchors' deferred queries and hands them
to `BookStore.filter_query()`, which ANDs the `BookMetadataFilter` bounds onto that query;
the node then counts the narrowed set. So the narrowing happens in SQL over the *whole*
upstream match, and what travels downstream is the narrowed query rather than a shortened
list. What the sketch was actually drawing still holds — the node searches for nothing and
can only shrink what the step it depends on found. An empty filter is refused at the store
rather than passed through, because a no-op narrowing step reports a count the user reads
as filtered.

**`Analyze_Recommend` applies its own bounds, inside its own search
(2026-08-19).** Case 62/64's expectation — bounds on a recommendation belong *in* the
recommend node — is implemented there rather than by delegating to `Filter_Retrieval`.
The node's argument parse is a **decomposition** into three parts, split by where each
one lands: `keywords` join the text that gets embedded, `bounds` (a `BookMetadataFilter`)
become WHERE clauses on the vector search itself, and `exclude` (an `ExclusionBookFilter`
— authors, titles, categories the ask ruled out by name) is a pure predicate over what
comes back.

The reason the bounds go *into* the search rather than onto its result is what
`search_by_embedding` actually does: it does not select a subset, it orders the whole
table by cosine distance and truncates at `limit`. A bound applied afterwards therefore
cuts an already-capped 50, and "like Dune, under 300 pages" can be left with two books,
because most Dune-adjacent books are long. Applied inside, all 50 fit and the ranking has
a real pool to choose from. The exclusions stay in Python on purpose — they are names the
model wrote from the user's phrasing, and a casefolded substring match finds "Frank
Herbert" from "Herbert" where SQL equality would silently exclude nothing.

This replaced a **delegation** (2026-08-17 – 2026-08-19) in which the parse produced a
natural-language `filter_query` and the executor ran `FilterRetrievalExecutor` as a
sub-workflow over its pool, wrapped as a query by `BookStore.isbn13_query()`. Three things
went wrong with it. The ask was parsed twice, with nothing happening between the two calls
— the filter node's parse read only what the recommend parse had written. The sub-workflow
carried UI it should not have: sections are opened by the *task runner*, so the filter
node's own `- N books left after: …` line and its preview cards landed inside the
Recommendation section, ahead of the recommendations. And it still filtered a capped pool.
`isbn13_query` and `keep_ranked` existed only to serve that hand-off and went with it.

The property that survives unchanged, and the one the taxonomy actually rests on: the
narrowing happens *before* the choice rather than after it, which is the whole objection to
a trailing `Filter_Retrieval`. The tool catalog is also unchanged — `RecommendationStrategy`
is fieldless and its docstring is still selection prose, while `RecommendationArgs` is an
internal tool the planner never sees.

**Cost, and a reversal.** Under the delegation, an ask whose bounds excluded everything
near the anchor *failed the goal*. It no longer does: `Analyze_Recommend` is the turn's
answer, so an empty match is a sentence it writes ("nothing that short sits near those
books") and the node still finalizes `ok`. `ok` claims *parsed and answered*, not *books
chosen* — the same way `num_books == 0` is a real answer for `Filter_Retrieval`. Raising
there would surface as the generic failure message and tell the user nothing about which
constraint was too tight. The reply is given the bounds in words and the pre-exclusion pool
size so it can say which.

**`Filter_Retrieval` may not depend on `Retrieve_Random` (2026-07-28).** That node returns
one arbitrarily chosen book, so narrowing it afterwards discards the pick far more often
than not, and the empty result is indistinguishable from "nothing matched". Bounds on a
surprise belong in `Retrieve_Random`'s own `filters`, where the pick is drawn from inside
them. Convention only — nothing in the schema rejects the edge, so it lives in both
docstrings and in the golden expectations.

**Union is both implicit and an explicit node.** `Combine_Union` / `UnionRetrieval` was
registered, removed the same day, then re-added (2026-07-24). The removal argument still
holds for the *implicit* case: listing several task ids in *any* node's `depends_on`
already means "pool what all of these found" — that is what the base suite's
two-bibliography cases (53, 60) and the compare cases rely on, with no union node in the
plan and the right answer. So `Combine_Union` is deliberately **not** required for pooling.
It earns its place only when the pooled set is itself a step something downstream consumes
— one ranked/sorted answer drawn from several sources, or a single list handed to one
analyze step. Its "Do not use" section says exactly this, to steer the planner away from
emitting it for plain side-by-side bibliographies.

**Accepted cost of re-adding it:** the ambiguity the "one operation per node" rule below
guards against comes partly back — a pooling request now has two defensible spellings
(implicit edges, or an explicit `Combine_Union`). The docstring narrows when to reach for
the node, but eval expectations that pin `Combine_Union` vs. bare edges have to pick one
and the golden test will hold the planner to it.

**The pooling rule stays load-bearing for executors.** A step with two or more
`depends_on` entries must union its inputs (dedup by ISBN13) before doing its own work,
whether or not an explicit `Combine_Union` sits in the plan. Nothing in the schema enforces
this — it is stated in the goal-generator prompt's rules block and in the combine nodes'
docstrings, and the executors have to honor it. A plan still cannot distinguish "meant to
pool" from "forgot to intersect" when it uses bare edges: both look like two edges into one
node, so `expected_nodes` diffing in `report_system_goals.py` cannot catch a dropped
intersect. That is a known blind spot, not an oversight.

The open question above ("one node with a filter object, or a family of single-dimension
filter nodes?") resolved to **one node with a filter object**, but a deliberately narrow
one. `Filter_Retrieval` carries `BookMetadataFilter`
(`db/schema/filter_schemas.py`) — pages, year, rating, ratings count, is_children — which
is `BooksFilter` minus every field that could serve as a search subject. No authors, no
categories, and critically **no `keywords` free-text field**: that field is what blurred
the old `Retrieve_by_Traits` into `Analyze_Recommend`, and leaving it out is what keeps
this node a narrowing operator instead of a second recommender.

**One operation per node.** `Combine_Intersect` carries no filters — an earlier cut gave
the set operators an optional `BookMetadataFilter` applied after the set operation, and
that was removed. Two reasons: every constraint then had two legal homes (inline on the
combine node, or a downstream `Filter_Retrieval`), which is precisely the kind of "either
parse is defensible" ambiguity the taxonomy decision was meant to eliminate; and it made
the combine nodes' catalog entries carry filter documentation that `Filter_Retrieval`
already owns. The cost is longer plans — "fantasy books by Sanderson over 400 pages" is
now four nodes — traded for one unambiguous home per operation.

`depends_on` moved from `AnalyzeBaseRequest` up to a new `DependentRequest` base, since
these nodes consume task output without analyzing it. The planner's dependency remapping
and topological sort gate on `DependentRequest`.

**Known limitation, plumbing now exists (2026-08-04):** `compose(queries, op="and")` pushes
the predicate into SQL as an `INTERSECT` over CTEs, which is what the paragraph below asks
for. The `Combine_Intersect` executor still has to be written, and the node is not
registered on `minimal_end_to_end_v1`. Original statement of the problem:

`Combine_Intersect` intersects *materialized* result sets,
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

### Generation node — **removed 2026-08-08**

> **Status: reverted.** `generation_node.py`, `PlanJaneOutput.generation_nodes` and the
> tests are deleted; recover them from git history if this is revisited. The section
> below is kept as the record of what was decided and why, since the reasoning (a fixed
> stage costs no catalog tokens and cannot be misrouted; every sink is the attachment
> point; 160 goldens would have to carry it as a goal) is what any second attempt should
> start from. What the plan renders today is goals only.
>
> The generic hook it used — `extra_nodes` on `get_goals_mermaid_diagram` /
> `get_parsed_mermaid_diagram` — was removed on 2026-08-10, along with
> `get_parsed_mermaid_diagram` itself: PlanJane is now the only thing in the app that
> renders a diagram, and the parsed-arguments one had no live caller. A future
> planner-attached node needs no hook to replace it, since the goal diagram builds a
> `list[MermaidBox]` — appending one more box is the seam. See
> `app/domains/planjane/dial/`.

Owns the final answer. Sketched fields: the **portion of the query** it is answering
(`str`), plus the upstream outputs it renders. Every retrieval and analyze node just
returns output data; generation is what the user reads, and it maps to the sections the
frontend already renders.

**Resolved 2026-07-28 — a fixed stage, not a planner goal.** `PlannerWorkflow` attaches
the answer stage itself (`app/domains/planner/generation_node.py`), so the LLM never
selects it: no catalog tokens, no misroute, and no plan can come back without an answer.
It is still drawn in both Mermaid diagrams, so the visibility a goal would have bought is
kept for free. The decider was the eval suites — as a goal, all 160 non-empty
`expected_nodes` would need it appended, for a check that cannot fail. Promoting a fixed
stage to a goal later is easy; demoting one after 160 goldens carry it is not.

**Attachment point: every sink** — a goal nothing else depends on. Not the deepest goal
and not the one with the most dependencies: a Compare fed by four retrievals is terminal
only when no Recommend consumes it, and an independent goal in a compound message is its
own sink at depth 0.

**Still open:** one generation node per sink (today's default, one answer per independent
branch) or one per turn owning ordering and framing across all of them
(`create_generation_nodes(..., single_answer=True)`). Per-sink means no one writes the
cross-section framing or reports a failure that spans branches; one-per-turn means a
compound message's unrelated answers get merged by a single writer. Most plans have
exactly one sink, so the two agree except on compound messages.

## Open questions

- ~~One filter node with a filter object, or several single-dimension filter nodes?~~
  Resolved 2026-07-24 — one node, one narrow filter object; see above.
- **Do the base suite's multi-anchor expectations still hold?** Cases 56, 57 and 59 were
  written on 2026-07-24 expecting a *single* `Retrieve_by_Author` with the genre silently
  dropped, because no combine operator existed. `Combine_Intersect` now gives that shape a
  correct plan (`Retrieve_by_Author` + `Retrieve_by_Genre` + `Combine_Intersect`), so those
  expectations describe the old world. They need re-deciding, not just re-running.
- ~~Is generation a planner goal or a fixed terminal stage?~~ Resolved 2026-07-28 — fixed
  stage, attached per sink; see above. One-per-sink vs one-per-turn is still open.
- ~~Does the CTE composition live in the executors or in `db/stores/book_store.py`?~~
  Resolved 2026-08-04 — **the store layer**. `db/stores/deferred_query.py` holds the
  carrier (`DeferredBookQuery`: a SELECT of isbn13 plus an optional `score`, with no LIMIT
  and no ORDER BY — the two invariants that make it composable), and `db/stores/utils.py`
  holds `build_title_query` / `build_count` / `compose` / `build_materialize`. Executors
  pass the object around and never write SQLAlchemy; otherwise every combine node grows
  its own copy of the composition rules.
  - **Revised 2026-08-17 — `utils.py` is gone; the derivations moved onto the carrier.**
    A count travelled executor → workflow helper → store method → builder function —
    two of those hops were pure plumbing. Now everything derivable from a built query
    is a method on `DeferredBookQuery` (`count_stmt()`, `materialize_stmt()`,
    `compose()`, which returns a wrapped query rather than a bare statement), and
    `BookStore` keeps only what a derivation can't do: build from a dimension
    (needs the model) and execute (needs the session). Executors still never write
    SQLAlchemy — the 2026-08-04 point stands, one file smaller.
- ~~Does retrieval-returns-counts change the retrieval **output contracts**?~~ Resolved
  2026-08-04 — yes, minimally. `BookRetrievalOutput` (`app/domains/books/schemas.py`) gains
  `num_books` (promoted off `FindByTitleOutput`, since every retrieval and combine node now
  reports one), `query_sql` (persisted, readable), and `query` (the carrier,
  `exclude=True`). `books` stays and stays empty until something materializes, so
  `num_books` is the size of the match and `len(books)` the size of the fetch.
  **The `exclude=True` is load-bearing:** `to_serializable` skips excluded fields but does
  walk `__pydantic_private__`, so a statement stashed as a private attr instead would reach
  the JSONB insert in `record_chat_run` and break it.
  - **Revised 2026-08-17 — `books` is gone from `BookRetrievalOutput` entirely.** "Stays and
    stays empty" did not survive contact: `BookWorkflow.preflight()` returned the count and a
    sample together, so every retrieval node had a few rows in hand and a field to put them
    in, and `num_books` vs `len(books)` was the only thing marking them as a preview rather
    than an answer. `preflight` is now split — `count_books()` stamps `query`/`query_sql`/
    `num_books` and fetches nothing; `preview_books()` is a `@task` returning rows the caller
    streams and drops — and the output shape carries no rows at all, so composing against
    `query` is the only thing a downstream node *can* do. A node that genuinely chooses rows
    declares its own field for them (`RecommendationOutput.books`), which reads as the
    different claim it is. Cost: a node wanting both a count and cards pays two round trips
    instead of one. The store-level halves of the old move went with it (also 2026-08-17):
    `BookStore.preview()` / `build_preview` (the one-round-trip `(total, sample)`) and the
    row-fetching `search_by_title` are deleted, so `count()` and `materialize()` are the
    only ways a deferred query meets the database.
- How does a mock executor represent "a query I have not run yet" so this can be tested
  before real executors exist? **Still open** — a mock leaves `query` as `None` today, and
  the terminal node then materializes nothing rather than falling back to `books`.
- **New, from building it:** `compose()` drops `score`, because a per-dimension similarity
  score means nothing across dimensions. So a pooled query ranks by rating, and a small
  `limit` on the pool can rank the actual anchor below its own sequels — "Dune" comes third
  behind two better-rated books in the Dune+Neuromancer pool. Carrying `max(score)` through
  the union would fix it; not built.

## Before building this

The planner side is settled enough to proceed (2026-07-24 baseline: 157/164, all reds
attributable to the unbuilt clarification node). What is *not* settled is whether to build
executors, generation, or human-in-the-loop first — that sequencing decision, and its
reasoning, is recorded in [../roadmap.md](../roadmap.md) under "Next move".
