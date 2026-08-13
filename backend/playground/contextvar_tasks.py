"""Does the ContextVar in airglider nest things correctly?

Run:  poetry run python playground/contextvar_tasks.py

Exercises the shipped mechanism (`airglider/src/context.py` — one ContextVar
plus `parent_scope`) through the real `@task` and `Workflow`, not a sandbox copy.

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
    # a hand-built envelope (demo 4) never ran through a scope, so it has no
    # duration of its own
    duration = f"{env.duration:>5}s" if env.duration is not None else "    —"
    print(
        f"{pad}{label:<28} id={env.id}  parent={parent:<12} "
        f"ok={str(env.ok):<5} {duration}  tokens={env.token_usage.total}{err}"
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
    print("   (its own 0.05 plus everything under it), func3 reads 0.30 at the")
    print("   bottom. Before, this collapsed to one envelope wearing func1's")
    print("   name and func3's id.")


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
    # nothing is threaded in — the workflow finds this task's envelope
    # through the ContextVar
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
    print("\n-> Four levels, alternating kinds. A @task's envelope holds children")
    print("   like any other, which is what makes this legal.")


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
    print("\n-> No cross-talk: gather() wraps each coroutine in a Task, which")
    print("   snapshots the context, so a set() inside one is invisible to its")
    print("   sibling. The copy is shallow, so the attach still mutates the")
    print("   real parent.")


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
    print("   envelope becomes a step of the published one and the wrapper")
    print("   reports it, because the published envelope is what `leaf` already")
    print("   attached to — handing back the other object would drop the subtree.")


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
        # the step attached itself on the way out and run_async_step attaches
        # it again: it must land once, and be billed once
        await self.run_async_step(billed())
        self.record.ok = True


async def demo_no_double_attach():
    banner(5, "run_async_step + auto-attach: attached once, counted once")
    record = await ExplicitWorkflow()()
    render(record)
    print(f"\nsteps={len(record.steps)}  tokens={record.token_usage.total}")
    print("\n-> One step, 7 tokens. `add_step` is idempotent: it skips a step")
    print("   already in `steps` (by identity), so the explicit call is a no-op.")
    print("   That is what lets both mechanisms be live at once.")


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
    print("\n-> The parent is ok=True with no error of its own — it caught")
    print("   nothing and returned normally. The failure sits one level down,")
    print("   where it happened. Promoting it is run_async_step's job.")


# ---------------------------------------------------------------------------
# 7. no parent
# ---------------------------------------------------------------------------


async def demo_orphan():
    banner(7, "Called from a script, with nothing above it")
    from airglider import current_parent

    print(f"current_parent() -> {current_parent()}")
    render(await leaf("standalone"))
    print("\n-> default=None, so the attach is skipped; a script or test calling")
    print("   a task directly still gets its envelope back.")


async def main():
    await demo_nested_tasks()
    await demo_interleaved()
    await demo_concurrent()
    await demo_custom_envelope()
    await demo_no_double_attach()
    await demo_failure_depth()
    await demo_orphan()

    print(f"\n{'=' * 78}")
    print("Every envelope attaches to whoever was current when it started,")
    print("exactly once, on the way out. Who may call whom stopped mattering.")
    print("Fire-and-forget still cannot work: a create_task outliving its parent")
    print("attaches to a record already serialized.")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    asyncio.run(main())
