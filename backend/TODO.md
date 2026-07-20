# TODO (scratchpad)

Durable planning lives in [/docs](../docs/README.md) — roadmap, backlog, eval strategy,
and design decisions. This file is only for in-flight scribbles that die within a
session; anything worth keeping graduates into a `docs/` file.

Migrated 2026-07-17: V1 scoping → `docs/design/node-taxonomy-v1.md` + `docs/roadmap.md`;
code-review/security findings, test gaps, workflow-framework notes → `docs/backlog.md`;
golden-test/suite notes → `docs/eval-strategy.md`. Historical cleanup logs live in git
history (`git log -p -- backend/TODO.md`).

---

(nothing in flight)

* add a intent field in the initial parse litteral
* add a prompt jection field (str or bool)
    * just refuse (or this can be part of the intent)
* add a complexity score or intent
    * stress testing, trying to break the system?
    * not reasonable query for a book recommender?
* maybe you'll need an entity thing
    * group them by books or reference books etc...

