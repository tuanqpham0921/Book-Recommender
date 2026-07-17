# backend/playground

Experimentation space. Two things live here that production code currently points at —
both on purpose, both temporary in different ways:

## `app_mock/executors/` — the mock executors

`app/registry.py` sets `EXECUTORS_CLS_MAPPING = MOCK_EXECUTORS_CLS_MAPPING` (marked
with a NOTE). Every node "executes" by streaming canned markdown / mock book data.
This is the placeholder until real domain executors are built (roadmap Phase 3), at
which point the mapping repoints and these mocks remain useful for tests.

## `app_mock/extended_registry.py` — the scaling extension (~18 extra node types)

FindByAuthor, SaveToReadingList, RateBook, ReadingPlan, and friends — schema-only node
types used to test how the planner behaves as the catalog grows
(`evals/suites/query_suite_extended.json` targets them).

**The toggle is manual and by design**: the "PLAYGROUND EXTENSION" block at the bottom
of `app/registry.py` folds these into the live registry; commenting out that one block
runs the app with only the real registered nodes, nothing else changes. The block is
currently **enabled**. The V1 release build ships with it commented out (release
checklist in [docs/roadmap.md](../../docs/roadmap.md)).

Extended nodes have no executors — if execution were enabled, they'd log
"No executor registered". A node that earns promotion moves to `app/domains/` via the
standard add-a-node path in [app/domains/README.md](../app/domains/README.md).
