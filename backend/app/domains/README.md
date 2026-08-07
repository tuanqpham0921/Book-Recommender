# backend/app/domains

The node type system — what the planner can plan with — plus the planner pipeline
itself. The V1 node set and its rationale live in
[docs/design/node-taxonomy-v1.md](../../../docs/design/node-taxonomy-v1.md).

## How it fits together

A capability is a **vertical slice**: one folder holding everything about one node.

```
books/find_by_title/
├── labels.py     # the planner-facing name, as a one-member str Enum
├── schemas.py    # request schema (docstring = tool description) + output schema
├── executor.py   # the NodeExecutor that runs it
└── __init__.py   # SPEC = NodeSpec(...) tying the three together
```

- `node_spec.py` — `NodeSpec` (node_type, tier, request, output, executor) and
  `NodeTier`. One spec per node; it is the **only** thing a slice has to export.
  Its `__post_init__` checks the spec's name against the request schema's
  `Literal` default, so the two cannot drift apart silently.
- `<domain>/guide.py` — that domain's specs as a tuple, one line per node.
- `app/registry.py` — composes the domain guides into `SPECS` and **derives**
  everything from it: `NODE_TYPE_TO_CLS`, the tier class tuples, `CATALOG_TIERS`,
  `AnyStrategyRequest`, `NodeTypeEnum` and the executor mapping. None of those
  are hand-maintained per node.
- `<domain>/schemas.py` — the domain's entity model plus the output shapes shared
  across its slices (`Book`, `BookRetrievalOutput`, …). A slice's own output
  subclasses the shape it claims in its docstring. One entity model per domain:
  don't add a narrower variant for a single consumer — narrow at the point of
  use instead (see `Book`'s docstring).
- `base_request.py` — `BaseRequest`, shared fields + validation.
- `node_executor.py` — `NodeExecutor`, the base every slice's executor subclasses.
  It pins the `run(task, dependent_results, request_context)` signature the task
  runner calls, and resolves the output type from `NodeExecutor[SomeOutput]`, so a
  slice's executor needs no `__init__`.
- `node_types.py` — just `UnknownNodeTypeEnum`. `NodeTypeEnum` is built in
  `app/registry.py`; it cannot live here without an import cycle back through the
  slices.
- `planner/` — the pipeline: `parse_intent.py` (message → goals),
  `args_parser.py` (goal → typed request), `main.py` (`PlannerWorkflow`: runs it,
  renders the Mermaid diagram, streams it). Prompts live in `planner/prompts/*.txt`.
- `task_runner.py` — `TaskRunnerWorkflow`, executes a classified plan via
  `registry.EXECUTORS_CLS_MAPPING`. Implemented, currently disabled in the orchestrator
  (executors are still mocks — see `playground/README.md`).

Request schemas describe *what* to do; **executors** (the *how*) are reached
through the slice's `NodeSpec` — schemas contain no execution logic.

## Adding a node (the standard path)

1. Create the folder `<domain>/<node>/` with the four files above.
2. Write the request schema's docstring for the LLM (include example queries;
   that's roadmap Phase 2 style). `make tools-catalog` audits every docstring for
   `Purpose: / Args: / Returns: / depends_on: / Use when: / Do not use: /
   Constraints:` plus an examples section (`Example queries:`, or example values
   like `Example genres:`). `Returns:` and `depends_on:` must name **output
   shapes**, not prose — `BookRetrievalOutput`, `BookRecommendationOutput`,
   `AnalyzeBooksOutput`, `ActionConfirmationOutput`, or a node-specific name for
   anything outside that vocabulary. That pairing is how the planner knows which
   nodes can legally feed which; the vocabulary is defined in
   `books/schemas.py`.
3. Subclass the output from the shape the docstring claims, and give **every
   output field a default** — the workflow builds the envelope by calling
   `output_type()` with no arguments.
4. Export `SPEC = NodeSpec(...)` from the slice's `__init__.py`.
5. Add that SPEC to the domain's `guide.py`. That is the only file outside the
   slice you touch.
6. Add eval cases with `expected_nodes` in `backend/evals/suites/` — see
   [docs/eval-strategy.md](../../../docs/eval-strategy.md).

Run `make tools-catalog` afterwards: it reads the live registry, so it confirms
the node reached the planner's catalog and flags a missing executor or docstring
section.

**Parking a node** — keeping the code but hiding it from the planner — is
removing its SPEC from the domain's `guide.py`. The slice stays importable; the
planner never lists it and refuses any goal targeting it.

The planner picks a registered node up automatically — no routing changes.
