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
* maybe you'll need an entity thing
    * group them by books or reference books etc...
* example mismatch for system goals
    * might better to have the llm_id and id switch
    * to internal id vs id
    * or you can go in an enumerate them 

decisions:
1. models mini vs nano and effort
    * or a bigger model (both cost more money and more tokens)
    * or you can see that the mini is good enough
        * and best effort inject them
        * or resolve them after (i do like this)
            * might be a good blend between intent and goals...
            * because you need the intent to know which one to clamps

    * or it's something with the parse intent
        * this becomes a massive if statement
        * I do like the system goals
        * bc if you do book reference/entity
            then you are also just linking the intent to reference/entity

