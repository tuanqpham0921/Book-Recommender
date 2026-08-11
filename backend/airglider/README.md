# airglider

Result envelopes and workflow scaffolding for async pipelines: every step
returns the same envelope, nothing crashes silently, and a finished run is one
tree you can persist, summarize, and cost.

## Use it

```python
from airglider import WorkFlowOperationResult, Workflow, task
```

`airglider/__init__.py` is the entire public surface. **Import from the package
root, never from `airglider.src.*`** — the internal layout is deliberately free
to move. A symbol that is not re-exported in `__init__.py` is not API.

| Import | What it is |
|---|---|
| `Workflow` | base class for a multi-step async process — subclass, override `run()` |
| `task` | decorator for a single async function |
| `StepFailure` | control-flow signal raised by `run_async_step` when a step fails |
| `WorkFlowOperationResult` | the envelope: `ok`, `input`, `steps`, `details`, `runtime_error`, `timing`, `token_usage` |
| `Response`, `Time` | the envelope's payload and timing sub-models |
| `TokenUsage`, `ModelUsage` | token counts, per-model split, and USD cost |
| `RuntimeErrorInfo` | serializable exception record |
| `cost_of`, `MODEL_PRICES`, `PRICES_CHECKED_ON`, … | the price table (see below) |
| `to_serializable`, `remove_empty_values`, `strip_zero_token_usage`, `now_iso`, `uuid_8` | serialization + identity helpers |

## The record tree, and `flatten()`

`add_step` is the only place parentage is known, so it is the only place
`parent_id` is set. A child cannot know its own parent — a `@task` is a plain
async function with no reference to its caller, and a `Workflow` is constructed
before anyone decides where its record hangs. Both come out orphans and the
attacher adopts them, which is why nothing has to be threaded into the
decorator. Stamping on attach rather than deriving it later is what carries the
link through serialization.

`flatten()` is then the tree as a **span list** — depth-first, parent before
child, each entry carrying its `parent_id` and (via `Time.end_time`) its own
interval. The nesting is rebuildable from the list alone, with no reference to
the tree, which is what a timeline or a per-step cost table wants. `to_summary()`
remains the shape for *reading* a run top to bottom.

Two things to know: in-memory entries come back by reference, and a record
reloaded from JSON has plain-dict children (`steps: list[Any]` does not
re-validate) which `flatten` validates into copies. Entries keep their own
`steps`, so for a flat table drop them at the point of use —
`[op.model_copy(update={"steps": []}) for op in record.flatten()]`.

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
3. **`record.py` holds `WorkFlowOperationResult`, and callers store it as `.record`** —
   three names for one thing (record / WorkFlowOperationResult / "envelope"). Cheapest
   to unify now, while the library has one consumer.
4. `exception.py` → `exceptions.py`; `schemas/` is a web-app word for what is
   really the core model.
5. Needs its own `pyproject.toml` and pytest config — the suite currently
   inherits `asyncio_mode = "auto"` from the host's.
