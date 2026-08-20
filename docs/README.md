# docs/

The durable planning layer for this repo. The `TODO.md` files in `backend/` and
`frontend/` are short-lived scratchpads — anything worth keeping graduates into a file
here. Eval campaign outputs (reports, notes per run) stay in `backend/evals/results/`.

## Doc map

| Doc | Purpose |
|---|---|
| [roadmap.md](roadmap.md) | V1 phases, release checklist, deferred features |
| [backlog.md](backlog.md) | Tiered work items (P1/P2/P3) with code references |
| [eval-strategy.md](eval-strategy.md) | The golden-test mechanism, suite inventory, latest findings, relabel plan |
| [design/node-taxonomy-v1.md](design/node-taxonomy-v1.md) | Decision record: the V1 node set and conversation contract |
| [design/planner-shape.md](design/planner-shape.md) | Decision record: capability nodes vs. entity + intent (accepted for V1), plus the open planner experiments |
| [design/execution-pipeline-v1.md](design/execution-pipeline-v1.md) | Design record (proposed): retrieve → filter → analyze → generate, and the three nodes it needs |
| [design/human-in-the-loop.md](design/human-in-the-loop.md) | Design record (proposed): pause / persist / resume — candidate pause points and known blockers |

## Conventions

- **Read the nearest README first.** Most backend/frontend folders have a `README.md`
  with the local context; read it before changing that folder.
- **Docs update with the code.** A change to routes, the node registry, enums, or the
  request flow updates the nearest README, `CLAUDE.md`'s architecture section, and the
  relevant doc here — in the same change.
- **Decision records** go in `design/`, one file per decision, dated, with the evidence
  that drove them.
