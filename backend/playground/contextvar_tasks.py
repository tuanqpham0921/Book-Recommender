"""Would a ContextVar let `@task` attach itself to its caller's envelope?

Run:  poetry run python playground/contextvar_tasks.py

The idea under test: instead of the parent adopting a child explicitly
(`run_async_step` -> `add_step`), a ContextVar holds "the envelope currently
being built", and the `@task` decorator reads it and attaches itself.

This file builds a minimal version of that on airglider's real envelopes and
then pokes at the cases that decide whether it is safe — nesting, concurrency,
leaks, orphans, and double-attach. Nothing here imports or modifies airglider's
own task.py; it is a sandbox for the semantics.

The short version of what it prints, if you don't want to run it:

  1. plain `await` SHARES the caller's context     -> auto-attach works
  2. a leaf task in the middle can't hold children -> grandchildren skip a level
  3. `gather`/`create_task` COPY the context       -> concurrent parents stay correct
  4. `set()` without `reset()` LEAKS on the plain-await path
  5. a task with no parent must handle an unset var
  6. fire-and-forget outlives its parent           -> steps land after finalize
  7. auto-attach + explicit add_step               -> double count, silently
"""

import asyncio
from contextvars import ContextVar
from functools import wraps

from airglider import OperationResult, TokenUsage, WorkFlowOperationResult

# ---------------------------------------------------------------------------
# the mechanism under test
# ---------------------------------------------------------------------------

# `default=None` matters: a task called outside any workflow reads this and
# must not explode. See demo 5.
CURRENT: ContextVar[WorkFlowOperationResult | None] = ContextVar(
    "current_envelope", default=None
)


def ctx_task(func):
    """`@task`, except it adopts itself into whatever envelope is current."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = OperationResult(name=func.__name__, ok=True)
        result.response.result = await func(*args, **kwargs)
        result.token_usage = TokenUsage(total=1)

        parent = CURRENT.get()
        if parent is not None:
            parent.add_step(result)  # stamps parent_id, rolls up token_usage
        return result

    return wrapper


class CtxWorkflow:
    """A workflow that publishes its own envelope as the current one.

    `try/finally` around the reset is not optional — demo 4 shows what happens
    without it.
    """

    def __init__(self, name, body, *, reset=True):
        self.name = name
        self.body = body
        self.reset = reset
        self.record = WorkFlowOperationResult(name=name, ok=True)

    async def __call__(self, *args, **kwargs):
        parent = CURRENT.get()
        token = CURRENT.set(self.record)
        try:
            await self.body(*args, **kwargs)
        finally:
            if self.reset:
                CURRENT.reset(token)
        if parent is not None:
            parent.add_step(self.record)
        return self.record


def render(env, indent=0):
    """Print an envelope tree the way `flatten()` would have to rebuild it."""
    pad = "  " * indent
    parent = env.parent_id or "-"
    # the payload is printed because two calls to the same function are
    # otherwise indistinguishable in the tree — which is the whole point of
    # demo 4
    label = f"{env.name}({env.result})" if env.result else env.name
    print(
        f"{pad}{label:<34} id={env.id}  parent={parent:<12} "
        f"tokens={env.token_usage.total}"
    )
    for step in getattr(env, "steps", []):
        render(step, indent + 1)


def banner(n, title):
    print(f"\n{'=' * 74}\n{n}. {title}\n{'=' * 74}")


# ---------------------------------------------------------------------------
# 1. plain `await` shares the caller's context
# ---------------------------------------------------------------------------


@ctx_task
async def fetch(name):
    await asyncio.sleep(0.01)
    return f"{name}-rows"


async def demo_sequential():
    banner(1, "Sequential: plain `await` runs in the caller's context")

    async def body():
        await fetch("a")
        await fetch("b")

    wf = CtxWorkflow("workflow", body)
    render(await wf())
    print("\n-> both tasks found the workflow's envelope and attached to it.")
    print("   This is the case auto-attach is designed for, and it works.")


# ---------------------------------------------------------------------------
# 2. a leaf task cannot hold children
# ---------------------------------------------------------------------------


@ctx_task
async def outer_task():
    # this task runs another unit of work. Its own envelope is a plain
    # OperationResult, which has no `steps`, so it cannot publish itself as
    # CURRENT. The child therefore attaches to whatever is above it.
    await fetch("inner")
    return "done"


async def demo_leaf_cannot_parent():
    banner(2, "A leaf task in the middle: grandchildren skip a level")

    async def body():
        await outer_task()

    wf = CtxWorkflow("workflow", body)
    render(await wf())
    print("\n-> `fetch` is a sibling of `outer_task`, not its child, and the")
    print("   workflow counts its tokens twice-over in shape (once via each).")
    print("   To nest correctly, `outer_task` needs `steps` — i.e. it is a")
    print("   Workflow, not a task. The ContextVar does not remove that rule,")
    print("   it just makes breaking it invisible.")


# ---------------------------------------------------------------------------
# 3. concurrency: Tasks get a *copy* of the context
# ---------------------------------------------------------------------------


async def demo_concurrent_parents():
    banner(3, "Concurrent workflows: each Task gets its own context copy")

    def make(name):
        async def body():
            await asyncio.gather(fetch(f"{name}-1"), fetch(f"{name}-2"))

        return CtxWorkflow(name, body)

    left, right = make("left-wf"), make("right-wf")
    for record in await asyncio.gather(left(), right()):
        render(record)

    print("\n-> No cross-talk. `asyncio.gather` wraps each coroutine in a Task,")
    print("   and a Task snapshots the context at creation — so each child sees")
    print("   the workflow that spawned it, and a `set()` inside one Task can")
    print("   never be observed by its sibling. Concurrency is the part that")
    print("   actually works.")


# ---------------------------------------------------------------------------
# 4. the leak: set() without reset() on the plain-await path
# ---------------------------------------------------------------------------


async def demo_leak():
    banner(4, "Leak: `set()` with no `reset()` bleeds into the caller")

    async def inner_body():
        await fetch("inner")

    async def outer_body():
        leaky = CtxWorkflow("leaky-wf", inner_body, reset=False)
        await leaky()
        # everything after this point in the SAME coroutine now writes into
        # leaky-wf's envelope instead of outer-wf's
        await fetch("after-leak")

    outer = CtxWorkflow("outer-wf", outer_body)
    render(await outer())
    print("\n-> `after-leak` landed under leaky-wf. A plain `await` does not")
    print("   restore anything on return, so the only thing standing between")
    print("   you and this is a try/finally in every publisher.")
    print("\n   Look at the token counts too: outer-wf reads 1 while the child")
    print("   it contains reads 2. `add_step` rolls usage up ONCE, at attach")
    print("   time — so any step that arrives at a child afterwards is missing")
    print("   from every ancestor's total. Same root cause as demo 6, and it")
    print("   is why a late attach is not just a cosmetic nesting problem.")


# ---------------------------------------------------------------------------
# 5. a task with no parent at all
# ---------------------------------------------------------------------------


async def demo_orphan():
    banner(5, "No workflow in scope: the var is unset")

    result = await fetch("standalone")
    print(f"CURRENT.get() -> {CURRENT.get()}")
    render(result)
    print("\n-> Fine, but note the envelope is simply dropped unless the caller")
    print("   keeps the return value. Auto-attach makes 'did this get recorded?'")
    print("   depend on ambient state rather than on the call site.")


# ---------------------------------------------------------------------------
# 6. fire-and-forget outliving its parent
# ---------------------------------------------------------------------------


async def demo_outliving_task():
    banner(6, "Fire-and-forget: a step lands after the parent finalized")

    background = None

    async def body():
        nonlocal background
        # create_task snapshots the context *now* — including this workflow's
        # envelope — but the coroutine runs later
        background = asyncio.create_task(slow_fetch())
        await asyncio.sleep(0)

    @ctx_task
    async def slow_fetch():
        await asyncio.sleep(0.05)
        return "late"

    wf = CtxWorkflow("workflow", body)
    record = await wf()
    print("at finalize:")
    render(record)

    await background
    print("\n0.05s later:")
    render(record)
    print("\n-> The envelope was already 'closed' and reported. A late step")
    print("   mutates it after the fact — and if it had been serialized in")
    print("   between, the stored tree and the in-memory one disagree.")


# ---------------------------------------------------------------------------
# 7. auto-attach alongside an explicit add_step
# ---------------------------------------------------------------------------


async def demo_double_attach():
    banner(7, "Both mechanisms at once: the step is counted twice")

    async def body():
        record = CURRENT.get()
        step = await fetch("a")  # already attached itself
        record.add_step(step)  # the explicit seam attaches it again

    wf = CtxWorkflow("workflow", body)
    result = await wf()
    render(result)
    print(f"\nsteps={len(result.steps)}  tokens={result.token_usage.total}"
          f"  (one operation, one token)")
    print("\n-> This is the migration hazard. `run_async_step` and auto-attach")
    print("   would both be live during any transition, and nothing errors —")
    print("   `add_step` appends unconditionally and `token_usage +=` doubles.")


async def main():
    await demo_sequential()
    await demo_leaf_cannot_parent()
    await demo_concurrent_parents()
    await demo_leak()
    await demo_orphan()
    await demo_outliving_task()
    await demo_double_attach()

    print(f"\n{'=' * 74}")
    print("Verdict: concurrency is the part that works (demo 3). What breaks")
    print("is everything about *scope* — nesting depth (2), publisher")
    print("discipline (4), whether a call is recorded at all (5), lifetime")
    print("(6), and coexistence with the explicit seam (7).")
    print(f"{'=' * 74}")


if __name__ == "__main__":
    asyncio.run(main())
