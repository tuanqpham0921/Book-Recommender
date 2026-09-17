# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md). Frontend items were migrated
2026-07-17: correctness bugs + refactors + accessibility + UI polish →
`docs/backlog.md` (session race and timeout fix are roadmap Phase 6); server-side stop
→ roadmap deferred list. Fixed items (mermaid securityLevel, fetch_api errors) are
recorded in git history.

Migrated 2026-09-07: the book-card scroll/hover ideas → `docs/backlog.md`, "UI polish pool".

This file is only for in-flight scribbles that die within a session.

---

Go through the codebase again
famaliarize yourself again with what changes

currently we need an generation node
some things to look out for

1. better contract or a "inflight" tasks
    a. so you can have 1 place to add things to it
    b. it doesn't matter that the planner do or emit
        however, it should emit tasks format for the system
2. you might want to do system goals then tasks under
    a. this is probably the best for later use rather than just adding a gneration node
3. you might need to have better artifacts/sources ...
    a. and the generation node should be with it


