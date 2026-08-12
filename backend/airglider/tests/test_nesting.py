"""Automatic nesting — one ContextVar, set and reset around each unit of work.

`add_step` is still the only place `parent_id` is stamped. What changed is who
calls it: instead of the caller remembering to route a step through
`run_async_step`, the caller publishes its own envelope for the duration of the
call (`parent_scope`) and the callee adopts itself on the way out.

The property under test is not "tasks can nest" for its own sake — it is that
**who may call whom stopped mattering**. A `@task` calling a `@task` used to
collapse into a single envelope wearing the outer name and the inner timing,
which is why the shape of the call graph had to be a rule. These tests pin the
behaviour that replaces that rule.
"""

import asyncio

import pytest

from airglider import (
    OperationResult,
    Response,
    TokenUsage,
    Workflow,
    current_parent,
    parent_scope,
    task,
)


def _names(record) -> list[str]:
    return [(step.name or "").split(".")[-1] for step in record.steps]


@task(log_info=False)
async def leaf(label="x"):
    return label


class Simple(Workflow):
    """A workflow whose body is supplied per test."""

    def __init__(self, body):
        super().__init__()
        self._body = body

    async def run(self, *args, **kwargs):
        await self._body(*args, **kwargs)
        self.record.ok = True


class TestNesting:
    async def test_a_task_that_calls_a_task_nests_instead_of_collapsing(self):
        """The original symptom: three levels reported as one."""

        @task(log_info=False)
        async def inner():
            return "c"

        @task(log_info=False)
        async def middle():
            await inner()
            return "b"

        @task(log_info=False)
        async def outer():
            await middle()
            return "a"

        record = await outer()

        assert _names(record) == ["middle"]
        assert _names(record.steps[0]) == ["inner"]
        # each level kept its own identity — the collapse used to leave one
        # envelope wearing the outer name and the inner id
        assert record.result == "a"
        assert record.steps[0].result == "b"
        assert record.steps[0].steps[0].result == "c"

    async def test_a_task_can_hold_children_at_all(self):
        """The envelope a `@task` publishes has `steps` like any other — under
        the old two-class split it was built as the leaf shape and could
        publish itself as parent but never adopt anything."""

        @task(log_info=False)
        async def parent():
            await leaf()
            return None

        record = await parent()
        assert _names(record) == ["leaf"]

    async def test_a_task_can_call_a_workflow(self):
        @task(log_info=False)
        async def runs_a_workflow():
            await Simple(lambda: leaf("inside"))()
            return "done"

        record = await runs_a_workflow()
        assert _names(record) == ["Simple"]
        assert _names(record.steps[0]) == ["leaf"]

    async def test_a_workflow_can_call_a_task_that_calls_a_workflow(self):
        @task(log_info=False)
        async def middle():
            await Simple(lambda: leaf("deep"))()
            return None

        record = await Simple(middle)()

        assert _names(record) == ["middle"]
        assert _names(record.steps[0]) == ["Simple"]
        assert _names(record.steps[0].steps[0]) == ["leaf"]

    async def test_nothing_attaches_when_there_is_no_parent(self):
        assert current_parent() is None
        record = await leaf("standalone")
        assert record.parent_id is None
        assert current_parent() is None


class TestConcurrency:
    async def test_concurrent_workflows_do_not_steal_each_others_steps(self):
        async def body(name):
            await asyncio.gather(leaf(f"{name}-1"), leaf(f"{name}-2"))

        left, right = Simple(body), Simple(body)
        a, b = await asyncio.gather(left("left"), right("right"))

        assert [step.result for step in a.steps] == ["left-1", "left-2"]
        assert [step.result for step in b.steps] == ["right-1", "right-2"]
        assert all(step.parent_id == a.id for step in a.steps)
        assert all(step.parent_id == b.id for step in b.steps)

    async def test_the_var_is_restored_after_a_nested_call(self):
        seen = []

        async def body():
            seen.append(current_parent())
            await leaf()
            seen.append(current_parent())

        record = await Simple(body)()
        assert seen == [record, record]
        assert current_parent() is None


class TestAttachedOnce:
    async def test_run_async_step_does_not_double_attach(self):
        """Both mechanisms are live; the step must land once and be counted once."""

        @task(log_info=False)
        async def billed():
            result = OperationResult(ok=True)
            result.token_usage = TokenUsage(total=7)
            return result

        class Explicit(Workflow):
            async def run(self):
                await self.run_async_step(billed())
                self.record.ok = True

        record = await Explicit()()
        assert len(record.steps) == 1
        assert record.token_usage.total == 7

    def test_add_step_refuses_a_step_claimed_by_another_parent(self, caplog):
        first = OperationResult(name="first")
        second = OperationResult(name="second")
        child = OperationResult(name="child", token_usage=TokenUsage(total=3))

        first.add_step(child)
        second.add_step(child)

        # the same envelope in two trees would count its spend in both
        assert len(second.steps) == 0
        assert second.token_usage.total == 0
        assert child.parent_id == first.id


class TestReturnedEnvelope:
    async def test_a_self_reported_result_becomes_a_step(self):
        """The `_check_table` shape: reports `ok` itself, and ran a step.

        The returned envelope is a unit of work in its own right, so it keeps
        its own id and details and hangs under the wrapper — which *reports* it:
        the wrapper's `ok` and payload are the child's.
        """

        @task(log_info=False)
        async def checks():
            await leaf("probe")
            return OperationResult(
                ok=False,
                details=["threshold not met"],
                response=Response(result=0, output_type="int"),
            )

        record = await checks()

        assert record.ok is False
        assert record.result == 0
        assert _names(record) == ["leaf", "checks:result"]
        assert record.steps[1].details == ["threshold not met"]

    async def test_the_payload_is_the_value_not_the_envelope(self):
        """`.result` must keep meaning "the value this produced".

        Storing the envelope there would also write the whole subtree twice —
        once under `steps`, once under `response`.
        """

        @task(log_info=False)
        async def reports():
            return OperationResult(
                ok=True, response=Response(result="rows", output_type="str")
            )

        record = await reports()
        assert record.result == "rows"
        assert record.response.output_type == "str"

    async def test_an_already_attached_child_is_not_attached_twice(self):
        """`return await inner()` — inner attached itself on the way out, so
        `add_step` no-ops and it appears once."""

        @task(log_info=False)
        async def passes_through():
            return await leaf("once")

        record = await passes_through()

        assert _names(record) == ["leaf"]
        assert record.result == "once"

    async def test_a_hand_built_steps_list_duplicates_and_should_not_be_used(self):
        """The one shape that still goes wrong, pinned so it is not a surprise.

        A task whose children already auto-attached must not *also* hand them
        back in a `steps=` list: the returned envelope becomes a step, and the
        children it carries are then in the tree twice. `add_step` cannot catch
        this — the outer object is new, only its contents are shared. The fix is
        at the call site: drop the redundant list (see `db/readiness.py`).
        """

        @task(log_info=False)
        async def both():
            child = await leaf("once")
            return OperationResult(ok=True, steps=[child])

        record = await both()
        appearances = [op for op in record.flatten() if op.name.endswith("leaf")]
        assert len(appearances) == 2

    async def test_the_returned_envelope_does_not_overwrite_the_timing(self):
        @task(log_info=False)
        async def slow():
            await asyncio.sleep(0.05)
            return OperationResult(ok=True)

        record = await slow()
        assert record.duration is not None and record.duration >= 0.05


class TestFailurePaths:
    async def test_a_crashing_nested_task_is_recorded_at_its_own_depth(self):
        @task(log_info=False)
        async def explodes():
            raise ValueError("nope")

        @task(log_info=False)
        async def calls_it():
            await explodes()
            return "survived"

        record = await calls_it()

        # the caller caught nothing and returned normally; the failure sits
        # where it happened. Promoting it is run_async_step's job, not the
        # decorator's.
        assert record.ok is True
        assert record.steps[0].ok is False
        assert record.steps[0].runtime_error.type == "ValueError"

    async def test_a_cancelled_step_still_attaches_to_its_parent(self):
        """`parent_scope` exits through `finally`, so the partial run is kept."""

        @task(log_info=False)
        async def never_finishes():
            await asyncio.sleep(10)

        class Cancelled(Workflow):
            async def run(self):
                await never_finishes()

        workflow = Cancelled()
        running = asyncio.create_task(workflow())
        await asyncio.sleep(0.01)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

        assert _names(workflow.record) == ["never_finishes"]
        assert workflow.record.steps[0].ok is False

    async def test_the_var_is_reset_even_when_the_body_raises(self):
        record = OperationResult(name="scope")
        with pytest.raises(ValueError):
            with parent_scope(record):
                assert current_parent() is record
                raise ValueError("boom")
        assert current_parent() is None


class TestTokenRollup:
    async def test_usage_rolls_up_through_every_level(self):
        @task(log_info=False)
        async def spends():
            result = OperationResult(ok=True)
            result.token_usage = TokenUsage(total=5)
            return result

        @task(log_info=False)
        async def middle():
            await spends()
            await spends()
            return None

        record = await Simple(middle)()

        # attaching on the way *out* is what makes this work: a record attached
        # before it ran would contribute zero to every ancestor
        assert record.steps[0].token_usage.total == 10
        assert record.token_usage.total == 10
