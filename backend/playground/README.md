# backend/playground

Experimentation space. Two things live here that production code currently points at —
both on purpose, both temporary in different ways:

## `app_mock/executors/` — the mock executors

`app/registry.py` sets `EXECUTORS_CLS_MAPPING = MOCK_EXECUTORS_CLS_MAPPING` (marked
with a NOTE). Every node "executes" by streaming canned markdown / mock book data.
This is the placeholder until real domain executors are built (roadmap Phase 3), at
which point the mapping repoints and these mocks remain useful for tests.

Since 2026-08-04 the real executors are reachable too: each slice's `NodeSpec`
carries one, and `app/registry.py` derives `NODE_EXECUTORS_CLS_MAPPING` from those.
Repointing is changing which of the two `EXECUTORS_CLS_MAPPING` is assigned. The
slice executors currently raise `NotImplementedError`, so that stays a one-line
change to make deliberately, not by accident.

## `app_mock/extended_registry.py` — the scaling extension (~16 extra node types)

SaveToReadingList, RateBook, ReadingPlan, and friends — schema-only node types used to
test how the planner behaves as the catalog grows
(`evals/suites/query_suite_extended.json` targets them). Two have graduated out and are
now V1 core: `FindByAuthorRetrieval` (2026-07-21) and `RandomBookRetrieval` (2026-07-28).
Their old entries here are left as commented-out one-liners marking the promotion, so
the extension's history stays readable.

**The toggle is manual and by design**: the "PLAYGROUND EXTENSION" block at the bottom
of `app/registry.py` folds these into the live registry; commenting out that one block
runs the app with only the real registered nodes, nothing else changes. The block is
currently **disabled** (on `minimal_end_to_end_v1`), which is also what the V1 release
build ships (release checklist in [docs/roadmap.md](../../docs/roadmap.md)).

**Caveat since the `NodeSpec` refactor** (pre-existing in effect, now explicit): these
schemas arrive as raw class tuples, not specs, so enabling the block adds them to the
catalog and `NODE_TYPE_TO_CLS` but **not** to `NodeTypeEnum` — the planner will refuse a
goal aimed at one. That is fine for measuring catalog size, which is what the toggle is
for. Give them real `NodeSpec`s before planning against them end to end.

Extended nodes have no executors — if execution were enabled, they'd log
"No executor registered". A node that earns promotion moves to `app/domains/` via the
standard add-a-node path in [app/domains/README.md](../app/domains/README.md).
