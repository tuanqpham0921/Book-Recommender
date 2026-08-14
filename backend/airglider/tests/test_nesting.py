"""Automatic nesting — one ContextVar, set and reset around each unit of work.

The caller publishes its own envelope for the duration of the call
(`parent_scope`) and the callee adopts itself on the way out, instead of the
caller routing every step through a method that attaches it.

The property under test is that **who may call whom stopped mattering**. A
`@task` calling a `@task` used to collapse into one envelope wearing the outer
name and the inner timing, which is why the call graph's shape had to be a rule.
"""

import asyncio

import pytest

from airglider import (
    OperationResult,
    Response,
    TokenUsage,
    Workflow,
    add_details,
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
        # each level kept its own identity
        assert record.result == "a"
        assert record.steps[0].result == "b"
        assert record.steps[0].steps[0].result == "c"

    async def test_a_task_can_hold_children_at_all(self):
        """A `@task`'s envelope has `steps` like any other."""

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
    async def test_explicit_add_step_does_not_double_attach(self):
        """Both mechanisms are live — `parent_scope` attaches on the way out and
        a caller may also call `add_step` — so the step must land once and be
        billed once."""

        @task(log_info=False)
        async def billed():
            # the task's own envelope: record_span published it before calling
            current_parent().token_usage = TokenUsage(total=7)
            return "done"

        class Explicit(Workflow):
            async def run(self):
                step = await billed()
                # already attached; the guard absorbs this
                self.record.add_step(step)
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

        # the same envelope in two trees would be billed twice
        assert len(second.steps) == 0
        assert second.token_usage.total == 0
        assert child.parent_id == first.id


class TestReturnedEnvelope:
    """A `@task` returns its payload; the envelope is the decorator's.

    Returning one used to mean "report `ok` yourself" or "hand back what I
    called". Both have better answers now — `ok` means ran-to-completion, and
    anything awaited inside already attached itself — so the shape is rejected
    rather than guessed at, since the two things it could mean differ.
    """

    async def test_returning_an_envelope_is_rejected(self):
        @task(log_info=False)
        async def reports():
            return OperationResult(
                ok=True, response=Response(result="rows", output_type="str")
            )

        record = await reports()
        assert record.ok is False
        assert record.runtime_error.type == "TypeError"
        assert "returns its payload" in record.runtime_error.message

    async def test_the_rejection_names_the_two_replacements(self):
        @task(log_info=False)
        async def reports():
            return OperationResult(ok=True)

        record = await reports()
        assert "unwrap()" in record.runtime_error.message
        assert "add_details" in record.runtime_error.message

    async def test_passing_a_step_through_means_unwrapping_it(self):
        """`return await inner()` is now `return (await inner()).unwrap()` —
        inner attached itself on the way out, so it appears exactly once and
        only its payload travels up."""

        @task(log_info=False)
        async def passes_through():
            return (await leaf("once")).unwrap()

        record = await passes_through()

        assert record.ok is True
        assert _names(record) == ["leaf"]
        assert record.result == "once"

    async def test_a_task_reports_details_on_its_own_record(self):
        """What a body uses instead of returning a hand-built envelope."""

        @task(log_info=False)
        async def checks():
            await leaf("probe")
            add_details("threshold not met")
            return 0

        record = await checks()

        assert record.ok is True
        assert record.result == 0
        assert "threshold not met" in record.details
        assert _names(record) == ["leaf"]

    async def test_a_rejected_envelope_does_not_overwrite_the_timing(self):
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

        # the failure sits where it happened; promoting it is the caller's
        # choice (`unwrap`), not the decorator's
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
            # a body writes usage onto the envelope it is already running in
            current_parent().token_usage = TokenUsage(total=5)
            return None

        @task(log_info=False)
        async def middle():
            await spends()
            await spends()
            return None

        record = await Simple(middle)()

        # attaching on the way *out* is what makes this work — a record
        # attached before it ran contributes zero to every ancestor
        assert record.steps[0].token_usage.total == 10
        assert record.token_usage.total == 10
