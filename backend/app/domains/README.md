# backend/app/domains

The node type system — what the planner can plan with — plus the planner pipeline
itself. The V1 node set and its rationale live in
[docs/design/node-taxonomy-v1.md](../../../docs/design/node-taxonomy-v1.md).

## How it fits together

- Each domain package (`books/`, `users/`, `project/`) defines:
  - a `node_types.py` enum (`BookNodeTypeEnum`, …) — the string names the planner emits;
  - `schemas/request_schemas.py` — pydantic **request schemas**, one per node type.
    **The class docstring is the tool description the planner LLM reads** (via
    `registry.catalog_entries()`), so docstrings here are prompt engineering, not
    comments.
- `node_types.py` (this folder) folds the domain enums into `NodeTypeEnum`.
- `base_request.py` — `DomainRequest`/`AnalyzeBaseRequest`, shared fields + validation.
- `planner/` — the pipeline: `parse_intent.py` (message → goals),
  `strategy_classification.py` (goals → typed strategies + dependency-ordered plan),
  `main.py` (`PlannerWorkflow`: runs both, renders the Mermaid diagram, streams it).
  Prompts live in `planner/prompts/*.txt`.
- `task_runner.py` — `TaskRunnerWorkflow`, executes a classified plan via
  `registry.EXECUTORS_CLS_MAPPING`. Implemented, currently disabled in the orchestrator
  (executors are still mocks — see `playground/README.md`).

Request schemas describe *what* to do; **executors** (the *how*) are looked up
separately by class in `EXECUTORS_CLS_MAPPING` — schemas contain no execution logic.

## Adding a node (the standard path)

1. Add the enum value in the domain's `node_types.py`.
2. Add the request schema in the domain's `schemas/request_schemas.py` — write the
   docstring for the LLM (include example queries; that's roadmap Phase 2 style).
3. Register it in `app/registry.py`: `NODE_TYPE_TO_CLS`, the domain class tuple, and
   the `AnyStrategyRequest` union.
4. Add an executor and map it in `EXECUTORS_CLS_MAPPING` (mock or real).
5. Add eval cases with `expected_nodes` in `backend/evals/suites/` — see
   [docs/eval-strategy.md](../../../docs/eval-strategy.md).

The planner picks the node up automatically from the registry — no routing changes.
