# backend/app/domains

The node type system — what the planner can plan with — plus PlanJane, the planner
itself. The V1 node set and its rationale live in
[docs/design/node-taxonomy-v1.md](../../../docs/design/node-taxonomy-v1.md).

## How it fits together

A capability is a **vertical slice**: one folder holding everything about one node.

```
books/find_by_title/
├── labels.py     # the planner-facing name, as a one-member str Enum
├── schemas.py    # request schema (docstring = tool description) + output schema
├── executor.py   # the executor that runs it (book nodes: a BookWorkflow)
└── __init__.py   # SPEC = NodeSpec(...) tying the three together
```

- `node_spec.py` — `NodeSpec` (node_type, tier, request, output, executor) and
  `NodeTier`. One spec per node; it is the **only** thing a slice has to export.
  Its `__post_init__` checks the spec's name against the request schema's
  `Literal` default, so the two cannot drift apart silently.
- `<domain>/guide.py` — that domain's specs as a tuple, one line per node.
- `app/registry.py` — composes the domain guides into `SPECS` and hands that
  tuple to one `Registry` (`REGISTRY`). **The specs are its only state**: it
  indexes them by `node_type` and answers everything as a read over that index
  — `spec()`, `request()`, `executor()`, `executors()`, `in_tier()`,
  `node_type in REGISTRY`, `catalog_entries()`, `format_catalog()`,
  `node_type_enum`, `request_union()`. Lookups take a `NodeTypeEnum` member or
  a plain string. Nothing is hand-maintained per node, and there are no longer
  parallel dicts (`NODE_TYPE_TO_CLS`, `CATALOG_TIERS`, the tier class tuples,
  `AnyStrategyRequest`, `EXECUTORS_CLS_MAPPING`) that could disagree.
- `<domain>/schemas.py` — the domain's entity model plus the output shapes shared
  across its slices (`Book`, `BookRetrievalOutput`, …). A slice's own output
  subclasses the shape it claims in its docstring. One entity model per domain:
  don't add a narrower variant for a single consumer — narrow at the point of
  use instead (see `Book`'s docstring).
- `<domain>/base_workflow.py` — the domain's base, holding what every node in it
  repeats. `books/base_workflow.py` is `BookWorkflow`: it exposes `self.store`
  (a property off the request context), and adds `preflight()` (stamp a deferred
  query on the output, get the match size and a small sample in one round trip)
  and `stream_books()` (cards to the browser, validated through `BookOut`).
- `base_request.py` — `BaseRequest`, shared fields + validation.
- `base_workflow.py` — `AppWorkflow`, the domain-agnostic base underneath those.
  It pins the **`run(query, artifacts)`** signature *every* unit of work in the
  app answers to, and resolves the output type from `AppWorkflow[SomeOutput]`,
  so a slice's executor needs no `__init__`. Nothing about one domain goes in
  here — that is what the domain base above is for. It also holds no
  LLM-request building: a slice writes its own `build_arg_parser_request(query)`
  and passes the result to `AppWorkflow.run_llm_args_parse`, which is the one
  shared seam. Only the prompt path (`ARG_PARSER_PROMPT_PATH`) is shared.

## One call shape: `run(query, artifacts)`

The planner, the parse step, the task runner and every node executor take the
same two arguments. `query` is whatever invoked this node — the user's text at
the top of a turn, a goal description further down. `artifacts` is what the
nodes before it produced, keyed by their goal id. A node's job is then always
the same: parse that input, reject it, or continue with it.

**Select artifacts by type, never by key.** `self.require_artifact(artifacts,
SomeOutput)` returns it typed or raises `StepFailure` (a controlled abort, not a
crash) — that is the reject arm, written once. Keys are provenance only, which
is what lets a node be fed by one upstream node or five without the caller and
the callee agreeing on a string. `ParsedDependents.from_results` in the
analyze_recommend slice follows the same rule.

**Services are not constructor arguments.** `AppWorkflow.__init__(ctx, messages)`
is the only `__init__` in the app layer; `sse_stream`, `llm_client`, `app_env`,
`session_id` and `user_message` are properties off the `RequestContext` it
holds. A workflow that needs a new service adds nothing to any call site.

**Stores are selected by type too.** `RequestContext.stores` is a
`dict[type, BaseStore]`; a node asks for its own with
`ctx.require_store(BookStore)`, and `BookWorkflow.store` is the one-line
shorthand for the common case of one store per node. A node needing *two*
should call `require_store` at the point of use rather than add a second
property. The check is on the value, not the key, so a domain base wired to
another domain's store raises there instead of failing at the first query —
and `RequestContext` never grows a field per domain.

Those stores are constructed on the FastAPI request-scoped session (see
`get_sqlalchemy_session` in `app/api/dependencies.py`). **Don't rebuild them
lazily from `ctx.session_factory`** — that opens a *different* session, so a
read in one node and a write in another quietly stop sharing a transaction.

## Naming: Workflow, Executor

The ladder is `airglider.Workflow` → `AppWorkflow` → `BookWorkflow`, each in a
`workflow.py`/`base_workflow.py` file. Concrete units of work are `*Workflow`
too: `TriageWorkflow`, `TaskRunnerWorkflow`.

(There used to be a rule that `Base` marks a reusable base class. It was retired
when the ladder collapsed to three levels — the file a class lives in already
says whether it is a base, and `AppBaseWorkflow`/`BookBaseWorkflow` read worse
than the thing they name.)

**`Executor` is the subset of those the planner can dispatch.** A
`FindByTitleExecutor` is a workflow like `TriageWorkflow` is, but it is also a
*node*: it has a request schema, a `NodeSpec`, a place in the tool catalog, and
the task runner reaches it through `REGISTRY.spec(...).executor` rather than
calling it directly. That is the distinction the second word is carrying — node vs.
pipeline step, not concrete vs. reusable. Rename it away and the class name
stops telling you the planner can reach it.

So: `<node>/executor.py` holding `<Node>Executor`, and `NodeSpec.executor`
pointing at it; `base_workflow.py` holding the bases they build on.
- `node_types.py` — just `UnknownNodeTypeEnum`. `NodeTypeEnum` is built in
  `app/registry.py`; it cannot live here without an import cycle back through the
  slices.
- `planjane/` — **the planner**. `schemas.py` (`SystemGoal`, `GoalParseRequest` —
  the tool call the LLM fills in), `executor.py` (`PlanJaneExecutor`: message →
  goals), and `mermaid.py` (the diagram — plan *presentation*, which the planner
  owns because the diagram is the plan rendered). Prompts live in
  `planjane/prompts/*.txt`. Schemas are split from the executor to match the
  slice layout used elsewhere (`schemas.py` + `executor.py`).

  What decides *whether* to call PlanJane — cache, small talk, out of scope —
  is `app/orchestration/triage.py`, not here: it is not a capability, and
  no `NodeSpec.executor` will ever point at it.
- `task_runner.py` — `TaskRunnerWorkflow`, executes a classified plan by
  resolving each goal to `REGISTRY.spec(goal.target_node_type)` and running its
  executor. `spec()` returning `None` means the node type is not registered;
  a spec with `executor is None` means registered but not yet runnable — the
  runner skips both, with different reasons. The mocks under
  `playground/app_mock/` are legacy eval-testing scaffolding — ignore them.

Request schemas describe *what* to do; **executors** (the *how*) are reached
through the slice's `NodeSpec` — schemas contain no execution logic.

## Adding a node (the standard path)

1. Create the folder `<domain>/<node>/` with the four files above. A book node's
   executor subclasses `BookWorkflow[TheOutput]` and implements
   **`run(query, artifacts)`** — the one call shape, same as everything else.
   (There is no `execute()` hook any more: it existed only to keep `run()` from
   being overridden while `run()` was where `self.store` got bound. `store` is a
   property now, so there is nothing to lose.)
   If the node needs its request schema filled in from the goal text, add a
   module-level `build_arg_parser_request(query) -> OpenAIParserRequest` beside
   the executor (copy one of the existing two — they are near-identical today,
   and that is on purpose: the duplication is what lets one node change model,
   prompt or message list without a flag on a shared base). Call it as
   `await self.run_llm_args_parse(build_arg_parser_request(query))` and assign
   `self.output.args` yourself — nothing does that for you.
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
