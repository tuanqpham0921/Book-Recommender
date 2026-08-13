"""The one ContextVar: which envelope is currently being built.

A child cannot know its caller, so the caller publishes its envelope for the
duration of the call and the callee adopts itself on the way out. Only
`task.wrapper` and `Workflow.__call__` use it.

A plain `await` shares the caller's context; `gather`/`create_task` copy it
(shallowly, so attaches still mutate the real record). Fire-and-forget
outliving its parent attaches to an already-serialized envelope — await
background work inside the scope that owns it.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .schemas.record import OperationResult

# default=None: a task with no workflow above it must simply not attach.
CURRENT_PARENT: ContextVar[OperationResult | None] = ContextVar(
    "airglider_current_parent", default=None
)


def current_parent() -> OperationResult | None:
    return CURRENT_PARENT.get()


@contextmanager
def parent_scope(record: OperationResult) -> Iterator[OperationResult]:
    """Publish `record` as current parent, then adopt it into the previous one.

    `parent_id` on the way in (earliest correct moment — a Workflow's envelope
    is built at construction, possibly under a different parent); the subtree on
    the way out (`add_step` sums `token_usage` once, at attach time).

    `reset` precedes the attach, or the record adopts itself. `finally` runs
    while a CancelledError propagates, so a cancelled run still attaches.
    """
    parent = CURRENT_PARENT.get()
    if parent is not None:
        record.parent_id = parent.id

    token = CURRENT_PARENT.set(record)
    try:
        yield record
    finally:
        CURRENT_PARENT.reset(token)
        if parent is not None:
            parent.add_step(record)
