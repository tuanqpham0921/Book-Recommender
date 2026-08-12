# airglider

Result envelopes and workflow scaffolding for async pipelines: every step
returns the same envelope, nothing crashes silently, and a finished run is one
tree you can persist, summarize, and cost.

## Use it

```python
from airglider import OperationResult, Workflow, task
```

`airglider/__init__.py` is the entire public surface. **Import from the package
root, never from `airglider.src.*`** — the internal layout is deliberately free
to move. A symbol that is not re-exported in `__init__.py` is not API.

| Import | What it is |
|---|---|
| `Workflow` | base class for a multi-step async process — subclass, override `run()` |
| `task` | decorator for a single async function |
| `StepFailure` | control-flow signal raised by `run_async_step` when a step fails |
| `OperationResult` | the one envelope: `ok`, `input`, `details`, `runtime_error`, `timing`, `token_usage`, `parent_id`, `steps` — plus `add_step` / `flatten` / `to_span` |
| `parent_scope`, `current_parent` | the nesting ContextVar (see below) |
| `Response`, `Time` | the envelope's payload and timing sub-models |
| `TokenUsage`, `ModelUsage` | token counts, per-model split, and USD cost |
| `RuntimeErrorInfo` | serializable exception record |
| `cost_of`, `MODEL_PRICES`, `PRICES_CHECKED_ON`, … | the price table (see below) |
| `to_serializable`, `remove_empty_values`, `strip_zero_token_usage`, `now_iso`, `uuid_8` | serialization + identity helpers |

## The record tree, and `flatten()`

**One envelope class.** `OperationResult` is a unit of work — id, parent,
timing, input, output, details, usage, error — and the `steps` it accumulated.
A `Workflow` and a `@task` produce the same thing; one that ran nothing else
just carries an empty `steps`.

There used to be a `WorkFlowOperationResult` subclass that added `steps`, on the
reasoning that a leaf has no children and should not carry the field. Two things
retired it. `steps` is not mandatory — an empty list costs nothing and `flatten`
reads it the same either way — and, more decisively, once nesting became
automatic (below) any unit of work can run another, so "which shape am I"
stopped being answerable at decoration time. What the split actually produced
was the same relationship rebuilt from several angles: an isinstance ladder in
`flatten`, a `getattr(x, "steps", [])` at every reader, and a rule about who was
allowed to call whom.

`add_step` is the only place parentage is known, so it is the only place
`parent_id` is set, and stamping on attach rather than deriving it later is what
carries the link through serialization. It is **idempotent**: a step that
already has a `parent_id` is skipped, and one claimed by a *different* parent is
refused and logged, since the same envelope in two trees would have its spend
counted in both.

## Nesting — the one ContextVar

A child cannot know its own parent: a `@task` is a plain async function with no
reference to its caller, and a `Workflow` is constructed before anyone decides
where its record hangs. So the *caller* publishes instead. `parent_scope(record)`
(`src/context.py`) sets `CURRENT_PARENT`, and in its `finally` resets it and then
attaches `record` to whatever was current before. `@task`'s wrapper and
`Workflow.__call__` are the only two call sites, which keeps the set/reset
discipline checkable by reading two files.

What follows from it:

- **Who calls whom stopped mattering.** A task may call a task, a workflow, or
  any mix; nothing is threaded through a signature and the tree still comes out
  right.
- **`run_async_step` is no longer what attaches a step** — the coroutine already
  ran inside the workflow's scope, and its `add_step` is a no-op the idempotency
  guard absorbs. What is left is the **failure policy**: mark the workflow
  not-ok and raise `StepFailure`, or hand the envelope back for a retry. Calling
  a step without it is legitimate and means "I'll decide what a failure means".
- **Attaching happens on the way out**, which the token rollup requires:
  `add_step` reads a child's usage once, at attach time, so a record attached
  before it ran would contribute zero to every ancestor. The cancel path comes
  free — `finally` runs while `CancelledError` propagates, so a step killed by a
  client disconnect still lands in its parent's `steps`.
- **Concurrency is safe.** A plain `await` shares the caller's context;
  `gather`/`create_task` copy it, so siblings each keep their own parent. The
  copy is shallow, so the attach still mutates the real record.
- **Fire-and-forget stays broken**, and cannot be fixed here: a `create_task`
  that outlives its parent attaches to an envelope already serialized and
  reported. Await background work inside the scope that owns it.

A `@task` that returns its own `OperationResult` — the "report `ok` myself
without raising" shape — has it **merged** into the published envelope rather
than handed back, since the published one is what this call's children attached
themselves to.

`flatten()` is then the tree as a **span list** — depth-first, parent before
child, each entry carrying its `parent_id` and (via `Time.end_time`) its own
interval. The nesting is rebuildable from the list alone, with no reference to
the tree, which is what a timeline or a per-step cost table wants. `to_summary()`
remains the shape for *reading* a run top to bottom.

No row drags a subtree, so the list does not re-encode the tree once per level:
every node goes through `to_span()` on the way in, which returns a shallow copy
carrying `steps=[]`. A node with no children has nothing to drop and comes back
**by reference**, which keeps flattening a mostly-free walk. `to_span()` is
`model_construct` over the shared fields rather than a dump-and-revalidate, so a
live payload stays the object the executor produced — and the sub-models are
shared with the tree node, making a span a view rather than an independent
record.

A record reloaded from JSON is the case to know about: `steps` is typed
`list[Any]` on purpose — pydantic would otherwise re-validate a child on
assignment and hand back a *copy*, breaking the one thing the tree depends on,
a step being the same object the workflow that produced it is still writing to.
The cost is plain-dict children after a round trip, which `flatten` validates on
the way past.

## `record.input` — what a unit of work was called with

Both `Workflow.__call__` and `@task` stamp it **before** the call, so a crashed
or cancelled step still records its arguments. Keyed by parameter name, so
`f(x)` and `f(arg=x)` record identically; a leading `self`/`cls` is dropped,
since the receiver of a decorated method is not an argument.

Values go through `to_record_input`, which differs from `to_serializable` in
the two ways a *call record* needs:

- **A value's own `to_summary()` wins.** One step's input is usually the step
  before it's output, and that output is already recorded in full on its own
  envelope — dumping it again grows the trace with the square of a pipeline's
  depth rather than its size. Give a big payload a `to_summary()` and it
  collapses everywhere at once (the host's `BaseLLMRequest` does this, so a
  prompt never lands in a record).
- **The result is always JSON-encodable.** Anything left over becomes
  `<TypeName>`. Arguments are not payloads a caller chose to record — they are
  whatever the function happens to take, and a live DB session or client
  reaching the envelope would break the host's insert far from where it came
  from.

Neither path raises: `to_summary` is host code this library does not control,
and bookkeeping that can take down the run it describes is a worse trade than
a missing field.

## The invariant

**airglider imports nothing from the host application.** That is what makes it
liftable into its own distribution, and it is the thing to protect when editing.
It is why the serialization helpers and the price table live in here rather than
being borrowed from the app's `common/`/`config/`.

To check the invariant still holds, import it with the host packages blocked:

```bash
poetry run python -c "
import sys
class B:
    def find_module(self, name, path=None):
        return self if name.split('.')[0] in {'app','common','config','clients','db','evals'} else None
    def load_module(self, name): raise ImportError(name)
sys.meta_path.insert(0, B()); import airglider; print('ok')"
```

The host's `common/utils` **re-exports** the helpers rather than keeping a second
copy, so `from common.utils import to_serializable` and `from airglider import
to_serializable` are the same function and cannot drift.

## Mermaid is not in here

It briefly was. It now lives at `app/domains/planjane/dial/`, because PlanJane
is the only thing that draws a diagram and is headed for being a service of its
own — the renderer has to travel with it. `dial/format.py` still imports
nothing but `airglider`, so nothing about that move loosened this package.

## Pricing is the one piece of policy

`src/config.py` holds a snapshot of one provider's prices on one date. Counting
and rolling up tokens is general; *what a token costs* is not. It lives inside
the package so `TokenUsage` can stamp `cost_usd` with no wiring from the host —
the tradeoff being that a host calling other providers has to edit that file.
If that becomes the norm, the seam to cut is `cost_of`: inject it instead of
importing it, and the module moves back out to the application.

Rates go stale. Re-verify and bump `PRICES_CHECKED_ON`. A model with no entry
lands in `unpriced_models` and contributes nothing to `cost_usd` — unknown
spend, deliberately not silent zero spend.

## Tests

```bash
make tests-airglider      # or: poetry run pytest airglider/tests/
```

They live beside the source so they travel with the package, and import only
from `airglider`. `tests/__init__.py` is what keeps their module names
namespaced against same-named files elsewhere in the host repo.

## Before extracting it

Known rough edges, in rough priority order:

1. **`src/` is nested inside the package**, so internal paths read
   `airglider.src.schemas.record`. The convention is `src/airglider/…` at repo
   root, or no `src` layer at all.
2. **`base_glider.py` contains `Workflow`** — the module is named for the
   metaphor, the class for the concept. Pick one axis.
3. **`record.py` holds `OperationResult`, and callers store it as `.record`** —
   three names for one thing (record / OperationResult / "envelope"). Cheapest
   to unify now, while the library has one consumer.
4. `exception.py` → `exceptions.py`; `schemas/` is a web-app word for what is
   really the core model.
5. Needs its own `pyproject.toml` and pytest config — the suite currently
   inherits `asyncio_mode = "auto"` from the host's.
