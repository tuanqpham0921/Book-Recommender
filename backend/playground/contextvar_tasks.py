"""Does the ContextVar in airglider nest things correctly?

Run:  poetry run python playground/contextvar_tasks.py

The earlier version of this file hand-rolled the mechanism to decide whether it
was safe. It is now shipped — `airglider/src/context.py`, one ContextVar plus
`parent_scope` — and the real `@task` and `Workflow` use it, so this file
exercises those instead of a sandbox copy.

What it checks, in order:

  1. task -> task -> task           nests three deep instead of collapsing
  2. workflow -> task -> workflow   the two kinds interleave freely
  3. concurrent workflows           no cross-talk between sibling Tasks
  4. custom envelope + children     `ok=False` survives, subtree survives
  5. run_async_step                 explicit attach does not double-count
  6. a failing nested task          the error sits at the depth it happened
  7. no parent at all               a task called from a script still runs

Durations are deliberately different per level, because "did func3's 0.3s get
reported as func1's total?" was the original symptom.
"""

import asyncio

from airglider import OperationResult, TokenUsage, Workflow, task


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def render(env, indent=0):
    pad = "  " * indent
    parent = env.parent_id or "-"
    name = (env.name or "?").split(".")[-1]
    payload = env.result
    label = f"{name}={payload}" if isinstance(payload, (str, int)) else name
    err = f"  !{env.runtime_error.type}" if env.runtime_error else ""
    print(
        f"{pad}{label:<28} id={env.id}  parent={parent:<12} "
        f"ok={str(env.ok):<5} {env.duration:>5}s  tokens={env.token_usage.total}{err}"
    )
    for step in getattr(env, "steps", []):
        render(step, indent + 1)


def banner(n, title):
    print(f"\n{'=' * 78}\n{n}. {title}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# 1. the original symptom: three nested tasks
# ---------------------------------------------------------------------------


@task(log_info=False)
async def func3():
    await asyncio.sleep(0.30)
    return "c"


@task(log_info=False)
async def func2():
    await asyncio.sleep(0.10)
    inner = await func3()
    return f"b({inner.result})"


@task(log_info=False)
async def func1():
    await asyncio.sleep(0.05)
    inner = await func2()
    return f"a({inner.result})"


async def demo_nested_tasks():
    banner(1, "task -> task -> task")
    render(await func1())
    print("\n-> Three envelopes, three ids, three durations. func1 reads ~0.45s")
    print("   (its own 0.05 plus everything under it) and func3 reads 0.30 at")
    print("   the bottom, which is the question 'where did the time go?' being")
    print("   answerable. Before, this collapsed to one envelope wearing func1's")
    print("   name, func3's id and func3's arguments.")


# ---------------------------------------------------------------------------
# 2. the two kinds interleave
# ---------------------------------------------------------------------------


@task(log_info=False)
async def leaf(label):
    await asyncio.sleep(0.01)
    return label


class InnerWorkflow(Workflow):
    async def run(self, label):
        await leaf(f"{label}-x")
        await leaf(f"{label}-y")
        self.record.ok = True


@task(log_info=False)
async def task_that_runs_a_workflow(label):
    # a @task calling a Workflow — the thing the "task can't call a workflow"
    # rule would have forbidden. Nothing is threaded in; the workflow finds
    # this task's envelope through the ContextVar.
    await InnerWorkflow()(label)
    return f"ran {label}"


class OuterWorkflow(Workflow):
    async def run(self):
        await task_that_runs_a_workflow("one")
        await leaf("loose")
        self.record.ok = True


async def demo_interleaved():
    banner(2, "workflow -> task -> workflow -> task")
    render(await OuterWorkflow()())
    print("\n-> Four levels, alternating kinds. `@task` now builds the tree-shaped")
    print("   envelope, so a task can hold children; that is the only change")
    print("   that makes this legal.")


# ---------------------------------------------------------------------------
# 3. concurrency
# ---------------------------------------------------------------------------


class ConcurrentWorkflow(Workflow):
    async def run(self, name):
        await asyncio.gather(leaf(f"{name}-1"), leaf(f"{name}-2"), func3())
        self.record.ok = True


async def demo_concurrent():
    banner(3, "Concurrent workflows: each Task carries its own copy")
    left, right = ConcurrentWorkflow(), ConcurrentWorkflow()
    for record in await asyncio.gather(left("left"), right("right")):
        render(record)
    print("\n-> No cross-talk. gather() wraps each coroutine in a Task and a Task")
    print("   snapshots the context at creation, so a set() inside one is")
    print("   invisible to its sibling. The copy is shallow — the envelope object")
    print("   is shared — so the attach still mutates the real parent.")


# ---------------------------------------------------------------------------
# 4. a task that builds its own envelope AND runs children
# ---------------------------------------------------------------------------


@task(log_info=False)
async def check_something():
    """The `_check_table` shape: reports ok itself, without raising."""
    child = await leaf("probe")
    return OperationResult(
        ok=False,
        details=[f"probe returned {child.result}", "threshold not met"],
    )


async def demo_custom_envelope():
    banner(4, "A task returning its own OperationResult, with a child underneath")
    record = await check_something()
    render(record)
    print(f"\ndetails = {record.details}")
    print("\n-> ok=False and the details survive; so does the child. The returned")
    print("   envelope is merged into the published one rather than handed back,")
    print("   because the published one is what `leaf` already attached to —")
    print("   returning the other object would have dropped the subtree.")


# ---------------------------------------------------------------------------
# 5. run_async_step alongside auto-attach
# ---------------------------------------------------------------------------


@task(log_info=False)
async def billed():
    result = OperationResult(ok=True)
    result.token_usage = TokenUsage(total=7)
    return result


class ExplicitWorkflow(Workflow):
    async def run(self):
        # the step attached itself on the way out; run_async_step attaches it
        # again. It must land once, and its 7 tokens must be counted once.
        await self.run_async_step(billed())
        self.record.ok = True


async def demo_no_double_attach():
    banner(5, "run_async_step + auto-attach: attached once, counted once")
    record = await ExplicitWorkflow()()
    render(record)
    print(f"\nsteps={len(record.steps)}  tokens={record.token_usage.total}")
    print("\n-> One step, 7 tokens. `add_step` is idempotent now: parent_id being")
    print("   set already is what marks a step as claimed, so the explicit call")
    print("   is a no-op. That is what lets both mechanisms be live at once.")


# ---------------------------------------------------------------------------
# 6. failure depth
# ---------------------------------------------------------------------------


@task(log_info=False)
async def explodes():
    raise ValueError("nope")


@task(log_info=False)
async def calls_the_exploder():
    await explodes()
    return "survived"


async def demo_failure_depth():
    banner(6, "A nested task that raises")
    render(await calls_the_exploder())
    print("\n-> The parent is ok=True with no error of its own: it caught nothing")
    print("   and returned normally. The failure is one level down, where it")
    print("   happened. Deciding that an ok=False child should fail the parent is")
    print("   still `run_async_step`'s job — the only thing it still does alone.")


# ---------------------------------------------------------------------------
# 7. no parent
# ---------------------------------------------------------------------------


async def demo_orphan():
    banner(7, "Called from a script, with nothing above it")
    from airglider import current_parent

    print(f"current_parent() -> {current_parent()}")
    render(await leaf("standalone"))
    print("\n-> default=None, so the attach is skipped. A startup hook or a test")
    print("   that calls a task directly still gets its envelope back.")


async def main():
    await demo_nested_tasks()
    await demo_interleaved()
    await demo_concurrent()
    await demo_custom_envelope()
    await demo_no_double_attach()
    await demo_failure_depth()
    await demo_orphan()

    print(f"\n{'=' * 78}")
    print("The rule is now: every envelope attaches to whoever was current when")
    print("it started, exactly once, on the way out. Who may call whom stopped")
    print("mattering. What still cannot work is fire-and-forget — a create_task")
    print("that outlives its parent attaches to a record already serialized.")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    asyncio.run(main())
