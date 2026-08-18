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

Those four files *are* the single-call template — `find_by_title/` is the
worked example (parse args → build the query → count → preview → finalize),
and a new node starts as a copy of it, not as a blank folder. A slice with
several LLM calls grows past those four files by one rule
(`analyze_recommend/` is the worked example): **executor.py stays the flow** —
`run()` plus every step, methods in the order `run` calls them, pure helpers
module-level beside them — and each **satellite module is one LLM call's pure
half** (the rendering, the tool model, the request builder — nothing that
runs). A builder with no rendering to carry (`build_arg_parser_request`) stays
in executor.py. Interpretation of the node's input gets its own module when it
outgrows `run` (`dependents.py`). Never a `utils.py` — a helper either belongs
to the flow, to one call's pure half, or to the input, and naming the file for
that is the point.

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
  (a property off the request context), and adds three `@task`s —
  `count_books()` (stamp a deferred query on the output and record the match
  size — no rows), `preview_books()` (a few rows off a query, handed back
  rather than written anywhere) and `materialize_books()` (pool upstream
  deferred queries into one anchor and fetch its rows) — plus `stream_books()`
  (cards to the browser, validated through `BookOut`). Counting and fetching
  are separate calls on purpose — `BookRetrievalOutput` has no `books` field,
  so rows a node only *showed* have nowhere to masquerade as rows it produced.
- `base_request.py` — `BaseRequest`, shared fields + validation.
- `node_input.py` — `WorkflowInput` / `NodeInput` / `ParsedInput`, and
  `build_input`, which fills a node's declared input from the goal text and its
  dependencies' outputs by matching on type. Imports nothing else from
  `app/domains/`; `base_workflow` imports *it*.
  `ParsedInput[SomeRequest]` is the *other* end of a node's entry: arguments
  someone already parsed, rather than text to parse. A node accepting both
  annotates `run` with the union (`PlanJaneInput`) and branches once, so the
  tool schema can be exposed and called directly — see `GoalParseRequest.__call__`,
  which is the shape `AppWorkflow.execute_tool_call` dispatches a parsed tool
  call into.
  It is parameterized rather than typed `BaseRequest` so the branch is a typed
  field, not a cast: a payload of the wrong schema fails building the input.
  PlanJane is its only consumer today — nodes stay NL-only until something
  needs the second entrance, so don't pre-build it into new slices.
- `base_workflow.py` — `AppWorkflow`, the domain-agnostic base underneath those.
  It pins the **`run(node_input)`** signature *every* unit of work in the
  app answers to, and resolves the output type from `AppWorkflow[SomeOutput]`,
  so a slice's executor needs no `__init__`. Nothing about one domain goes in
  here — that is what the domain base above is for. It also holds no
  LLM-request building: a slice writes its own `build_arg_parser_request(query)`
  and passes the result to `AppWorkflow.run_llm_args_parse`, which is the one
  shared seam. Only the prompt path (`ARG_PARSER_PROMPT_PATH`) is shared.
  `run_llm_args_parse` returns the first tool call's parsed arguments and
  records the tool result immediately — too early to wrap in a retry, and the
  reason `run_llm_tool_calls` exists beside it: it hands back the calls
  themselves, so a node that cares can close the [tool_call, tool result] pair
  *after* processing (and on the failure path, which is what keeps the message
  list valid for the rest of the turn).

## One call shape: `run(node_input)`

The planner, the task runner and every node executor take one argument: their
own `WorkflowInput` subclass (`node_input.py`). A node declares that class,
lists it on `NodeSpec.input`, and the task runner assembles it — so a node's
job is always the same: parse what it was given, or continue with it.

**The declaration is the point.** It replaced `(query, artifacts:
dict[str, Any])`, which could tell a node that something was missing but never
*what* — so a node short of a dependency could only raise. `RecommendInput`
declares `anchors: list[BookRetrievalOutput] = []`, and an empty list is a
named, visibly unfilled slot: enough for the node to fall back on the goal text
today, and enough to ask the planner for a goal that fills it later. Default a
field whenever the node has a real fallback; make it required only when the
node genuinely cannot proceed.

**Fields are filled by type, never by key.** `build_input` walks the input's
annotations and matches each against the dependency outputs — `X` takes the
first match, `X | None` takes it or None, `list[X]` takes all of them. Keys are
provenance only, which is what lets a node be fed by one upstream node or five
without the caller and the callee agreeing on a string. A required field that
matches nothing raises `ValidationError` **naming the field**, which the runner
turns into a skipped goal (`_prepare`) — that error text is the payload an
agentic runner would hand back to the planner.

`FilterRetrievalInput.anchors` is the first required dependency field, and it
shows what "required" costs for a list: `build_input` fills a `list[X]` with
every match, and an empty list is still a *filled* field, so the requirement has
to be `Field(..., min_length=1)`. A bare `...` would never fire. Only reach for
it when the node has no fallback at all — bounds with nothing to bound cannot
be run against the whole catalog and mean something else entirely.

**Services are not constructor arguments, and are not on the input.**
`AppWorkflow.__init__(ctx, messages)` is the only `__init__` in the app layer;
`sse_stream`, `llm_client`, `app_env`, `session_id` and `user_message` are
properties off the `RequestContext` it holds. Context and input split on
lifetime: services are built once per HTTP request, an input is assembled per
dispatch.

**A node declares the services view it needs too**, as `NodeSpec.context`.
`RequestContext.stores` is a `dict[type, BaseStore]` — the opaque carrier that
lets `app/common/` hold a `BookStore` without importing the books domain — and
a domain turns it into a typed field with a `narrow()`:
`BookRequestContext.narrow(ctx)` resolves `store` once, at dispatch, so a
request missing it fails there (naming the store) rather than at the first
query. `BookWorkflow.store` is then a plain field read, and `RequestContext`
never grows a field per domain.

Those stores are constructed on the FastAPI request-scoped session (see
`get_sqlalchemy_session` in `app/api/dependencies.py`). **Don't rebuild them
lazily from `ctx.session_factory`** — that opens a *different* session, so a
read in one node and a write in another quietly stop sharing a transaction.

## Naming: Workflow, Executor

The ladder is `airglider.Workflow` → `AppWorkflow` → `BookWorkflow`, each in a
`workflow.py`/`base_workflow.py` file. Concrete units of work are `*Workflow`
too: `TriageWorkflow`, `TaskRunnerWorkflow`.

The bottom rung is a **separate library**, and its rules are not restated here:
what `ok` means, when a producer raises instead of reporting, the two verbs for
running a step (`await step` vs `(await step).unwrap()`), and where
`add_details` lands all live in
[airglider's README](../../airglider/README.md#the-rules). Read it before
writing an executor — the executor is the producer in every one of those rules.

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
- `UnknownNodeTypeEnum` lives in `app/registry.py` beside the `NodeTypeEnum`
  it complements (the old `node_types.py` module here is gone — neither enum
  can live under `domains/` without an import cycle back through the slices).
- `planjane/` — **the planner**, split three ways, matching the slice layout
  used elsewhere. `external.py` is what the plan *is* and the address every
  other layer imports it from: `SystemGoal`, `PlanJaneOutput`, and
  `ExecutionOrder` with `execution_order()`, the dependency layering the task
  runner consumes. `schemas.py` is what the LLM fills in (`GoalParseRequest`,
  `MAX_SYSTEM_GOALS`). `executor.py` runs (`PlanJaneExecutor`: message →
  goals). The dependency runs `external ← schemas ← executor`, so a consumer of
  the plan pulls in neither the prompt example nor the executor — import from
  the `planjane` package root and the split stays free to move. Prompts live in
  `planjane/prompts/*.txt`.
- `planjane/dial/` — how PlanJane *shows* a plan, and the only Mermaid code in
  the app. `mermaid.py` turns goals into `MermaidBox`es — what a box says, and
  the `depends_on` → `sent_to` inversion — and `format.py` turns boxes into the
  diagram string (markup, orientation, emission). It lives under the planner
  because the diagram *is* the plan rendered, so a caller that drew it would be
  doing the planner's job; `PlanJaneExecutor.send_mermaid` stamps the result
  onto `PlanJaneOutput.diagram`.

  **`dial/` imports nothing from `app/`.** `format.py`'s only import is
  `airglider`, which is itself standalone, and `mermaid.py` adds nothing beyond
  it — so the subpackage runs with no `app` package present at all. That is
  deliberate: PlanJane is headed for being a service of its own, and this is
  the corner already free to travel. Import from `dial`, not from its modules.

  What decides *whether* to call PlanJane — cache, small talk, out of scope —
  is `app/orchestration/triage.py`, not here: it is not a capability, and
  no `NodeSpec.executor` will ever point at it.
- `TaskRunnerWorkflow` lives in **`app/orchestration/task_runner.py`** (it
  dispatches capabilities rather than being one, like Triage). It takes a
  `TaskRunnerInput(plan=...)` and nothing else — no `query`, because its work
  is driven entirely by the plan. `_prepare` is the one gate every goal passes:
  resolve the spec, check it has an executor, narrow the context, assemble the
  input. All four ways of failing skip that single goal and leave the rest of
  the plan running, with different reasons logged. The mocks under
  `playground/app_mock/` are legacy eval-testing scaffolding — ignore them.

Request schemas describe *what* to do; **executors** (the *how*) are reached
through the slice's `NodeSpec` — schemas contain no execution logic.

## Writing an executor — the rules

The shape every node follows, distilled from the live slices. The airglider
half of the contract — what `ok` means, when a producer raises, the two step
verbs — is in [airglider's README](../../airglider/README.md#the-rules) and is
assumed, not restated, here.

1. **One tool schema, one executor — 1-1.** A node is its request schema plus
   the workflow that serves it. New behavior is a new slice with a new `SPEC`,
   never a flag on an existing executor and never one executor reached two
   ways. Reworking how a node runs is a new spec too; park the old one.
2. **The body runs parse → work → finalize.**
   *Parse*: fill the node's own request schema from the goal text
   (`build_arg_parser_request(query)` → `run_llm_args_parse`) and stamp it on
   the slice's `args` field — the record of what this node thought it was
   asked, even when it only restates the goal. *Work*: whatever the node is
   for; artifact prep may precede the parse (the recommend node materializes
   its anchor first). *Finalize*: `self.finalize_result()` last. Each slice
   overrides it to compute the node's **claim** — "did I fill in what I
   promised": find_by_title claims args-parsed-and-query-built (zero matches
   is still ok), recommend claims args-parsed-and-books-chosen. Raise when the
   node cannot proceed; never hand-set `ok=False` and return.
3. **`@task` or `Workflow` everything async** — every DB round trip, LLM call
   and embedding is a step with its own duration, failure and spend. The
   ladder, smallest rung that fits:
   - a **pure function** for building requests (`build_*_request`) — sync, no
     I/O, testable without a workflow;
   - the **`run_llm_*` helpers** for LLM calls — `AppWorkflow`'s thin `@task`
     wrappers (`llm_execute`, `get_embeddings`, `execute_tool_call`) are the
     steps. **clients/ itself is tracing-free**: a client method raises and
     returns its payload, and never grows a `@task` — the app decides what is
     a step;
   - a **`@task` method** for an async unit that returns a payload
     (`count_books`, `preview_books`, `similarity_search`);
   - a **`Workflow`** only when the sub-work needs its own declared output
     type and envelope — the Triage → PlanJane shape. A node that runs another
     node starts it as a workflow and `.unwrap()`s (or reads the envelope,
     when a failure means something specific to this caller).
4. **Nodes hear natural language and typed artifacts, nothing else.** The goal
   text is `node_input.query`; upstream output arrives only through declared
   input fields, filled by type. The input contract does *selection*;
   interpretation is the executor's own job (`ParsedDependents`). Duck-type
   (`getattr`) only shapes that are still reserved names — the moment a shape
   has a class, read the typed field.
5. **Book nodes open counts-first**: parse args → build the deferred query →
   `count_books()` → `preview_books()` for the section's sample cards →
   hand the *query* downstream on the output. Rows are fetched once, at the
   end of the plan (`materialize_books`, or the terminal node's answer).
6. **Two traps with no compiler behind them**: every output field needs a
   default (the workflow constructs its output empty, before `run`), and a
   workflow instance is single-use — construct a new one per execution,
   including retries.
7. **Reuse before adding.** Most of what a new node needs is already on
   `BookWorkflow`, `DeferredBookQuery`, `REGISTRY` or `airglider` — see
   "Before Generating New Code" in the root `CLAUDE.md`, which also names the
   duplication here that is deliberate (`build_arg_parser_request` per slice)
   and must not be factored together.

One known wart, deliberately deferred: a business dead-end that raises and a
genuine bug both land in `runtime_error` (a `StepFailure` is stamped like any
other failure), so the record cannot yet tell "could not proceed" from
"crashed". The discriminated-error redesign is parked — don't build logic that
branches on `runtime_error.type`.

## Adding a node (the standard path)

1. Create the folder `<domain>/<node>/` by **copying the matching template** —
   `find_by_title/` for a single-call node, `analyze_recommend/` for a
   multi-step one — rather than writing the four files from scratch. A book
   node's executor subclasses `BookWorkflow[TheOutput]` and implements
   **`run(node_input)`** — the one call shape, same as everything else.
   (There is no `execute()` hook any more: it existed only to keep `run()` from
   being overridden while `run()` was where `self.store` got bound. `store` is a
   property now, so there is nothing to lose.)
   If the node needs its request schema filled in from the goal text, add a
   module-level `build_arg_parser_request(query) -> OpenAIParserRequest` beside
   the executor (copy one of the existing two — they are near-identical today,
   and that is on purpose: the duplication is what lets one node change model,
   prompt or message list without a flag on a shared base). Call it as
   `await self.run_llm_args_parse(build_arg_parser_request(node_input.query))`
   and assign `self.output.args` yourself — nothing does that for you.
1b. Declare the node's input in `external.py` as a `NodeInput` subclass. A node
   with no dependencies subclasses it and adds nothing — that empty class is a
   real statement, since it means the node *structurally* cannot consume
   upstream output. A node that consumes books adds
   `anchors: list[BookRetrievalOutput] = Field(default_factory=list)`; default
   it unless the node truly cannot run without one.
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
4. Export `SPEC = NodeSpec(...)` from the slice's `__init__.py`, naming the
   `input=` and `context=` you declared (both default, so a dependency-free
   node with no store needs neither).
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
