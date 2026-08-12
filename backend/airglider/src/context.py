"""The one ContextVar: which envelope is currently being built.

`add_step` is still the only place parentage is stamped — this module just
answers the question a child could never answer for itself ("who called me?")
by having the *caller* publish its own envelope for the duration of the call.
A `@task` or a `Workflow` then adopts itself on the way out, so nesting no
longer depends on the caller remembering to pass its record down or to route
the call through `run_async_step`.

**One variable, set and reset around each unit of work.** Nothing else reads or
writes it. That is deliberate: a ContextVar that carries state a trace depends
on is only safe while the set/reset discipline is airtight, and one context
manager used by exactly two call sites (`task.wrapper` and `Workflow.__call__`)
is a discipline that can be checked by reading two files.

Two asyncio facts this rests on:

- a plain `await` runs in the **caller's** context, so a nested call sees the
  envelope its caller published;
- `gather`/`create_task` **copy** the context at Task creation, so concurrent
  siblings each keep their own parent and a `set()` inside one can never be
  observed by another. The copy is shallow — the envelope object itself is
  shared — so a child attaching from inside a Task still mutates the real
  parent record.

Fire-and-forget is the case that stays wrong, and cannot be fixed here: a
`create_task` that outlives its parent attaches to an envelope that has already
been serialized and reported. Await your background work inside the scope that
owns it.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .schemas.record import OperationResult

# `default=None` matters: a task called with no workflow above it — a script, a
# test, a startup hook — reads this and must simply not attach.
CURRENT_PARENT: ContextVar[OperationResult | None] = ContextVar(
    "airglider_current_parent", default=None
)


def current_parent() -> OperationResult | None:
    """The envelope a step started right now would attach itself to."""
    return CURRENT_PARENT.get()


@contextmanager
def parent_scope(record: OperationResult) -> Iterator[OperationResult]:
    """Publish `record` as the current parent, then adopt it into the previous one.

    Both halves are in the `finally`, and the order is not interchangeable:
    `reset` first so that the attach below reads the *outer* envelope rather
    than the one we just published — otherwise a record would adopt itself.

    Attaching on the way **out** rather than on the way in is what keeps
    `add_step`'s token rollup correct. Usage is summed once, at attach time, so
    a record attached before it ran would contribute zero and every ancestor
    would under-count. By the time this exits, `record` is final.

    That also means the cancel path records more than it used to: `finally`
    runs while `CancelledError` is propagating, so a workflow killed by a
    client disconnect still lands in its parent's `steps` with whatever it had
    managed to do.
    """
    token = CURRENT_PARENT.set(record)
    try:
        yield record
    finally:
        CURRENT_PARENT.reset(token)
        parent = CURRENT_PARENT.get()
        if parent is not None:
            parent.add_step(record)
