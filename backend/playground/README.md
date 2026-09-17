# backend/playground

Experimentation space. Two things live here that production code currently points at —
both on purpose, both temporary in different ways:

## `app_mock/executors/` — the mock executors

**No longer wired.** Every node here "executes" by streaming canned markdown / mock book
data. This was the placeholder until real domain executors existed; since 2026-08-04
each slice's `NodeSpec` carries a real executor, and as of 2026-08-10 the registry has
no `EXECUTORS_CLS_MAPPING` to repoint — the task runner reads `NodeSpec.executor`
directly. The mocks are kept only as reference; nothing in the app imports them.

## `app_mock/extended_registry.py` — the scaling extension (~16 extra node types)

SaveToReadingList, RateBook, ReadingPlan, and friends — schema-only node types used to
test how the planner behaves as the catalog grows
(`evals/suites/query_suite_extended.json` targets them). Two have graduated out and are
now V1 core: `FindByAuthorRetrieval` (2026-07-21) and `RandomBookRetrieval` (2026-07-28).
Their old entries here are left as commented-out one-liners marking the promotion, so
the extension's history stays readable.

**The comment-toggle is gone (2026-08-10).** The "PLAYGROUND EXTENSION" block at the
bottom of `app/registry.py` mutated the module-level dicts (`NODE_TYPE_TO_CLS`,
`CATALOG_TIERS`, the tier class tuples) that the `Registry` refactor removed, so it was
deleted rather than left as commented-out code that could no longer work. It had been
**disabled** since `minimal_end_to_end_v1` anyway, which is what the V1 release build
ships (release checklist in [docs/roadmap.md](../../docs/roadmap.md)).

Folding these back in is now *simpler*, not harder: give them real `NodeSpec`s and pass
them alongside `SPECS` — `Registry(SPECS + EXTENDED_SPECS)` — instead of mutating four
globals. That also fixes the old caveat: because they arrived as raw class tuples they
joined the catalog but **not** `NodeTypeEnum`, so the planner refused any goal aimed at
one. Fine for measuring catalog size, useless for planning end to end; specs remove the
distinction.

Extended nodes have no executors — if execution were enabled, they'd log
"No executor registered". A node that earns promotion moves to `app/domains/` via the
standard add-a-node path in [app/domains/README.md](../app/domains/README.md).
