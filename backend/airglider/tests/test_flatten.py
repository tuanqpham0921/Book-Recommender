"""`flatten()` and `parent_id` — the trace tree as a span list.

The two go together: flattening is only useful if the nesting survives it, and
what makes it survive is `add_step` stamping `parent_id` when it attaches a
child. That stamp is asserted here rather than in the attach tests because it
exists *for* this — a flat list whose entries can be re-nested from their own
fields, with no reference to the tree they came from.
"""

import asyncio

import pytest

from airglider import WorkFlowOperationResult, Workflow, task


def _op(name: str) -> WorkFlowOperationResult:
    return WorkFlowOperationResult(name=name, ok=True)


def _tree() -> WorkFlowOperationResult:
    """root ─┬─ a ─┬─ a1
    │      └─ a2
    └─ b"""
    root, a, b = _op("root"), _op("a"), _op("b")
    a.add_step(_op("a1"))
    a.add_step(_op("a2"))
    root.add_step(a)
    root.add_step(b)
    return root


class TestParentId:
    def test_add_step_stamps_the_child(self):
        parent, child = _op("parent"), _op("child")
        parent.add_step(child)

        assert child.parent_id == parent.id

    def test_a_root_has_no_parent(self):
        assert _tree().parent_id is None

    def test_a_child_cannot_know_its_own_parent(self):
        """Which is the whole reason the stamp lives in `add_step`: an envelope
        is built before anyone decides where it hangs, so it comes out an
        orphan and is adopted on attach."""
        assert _op("orphan").parent_id is None

    async def test_a_task_envelope_is_adopted_by_the_workflow_that_ran_it(self):
        """Nothing is threaded into the decorator — a `@task` is a plain async
        function with no reference to its caller."""

        @task(log_info=False)
        async def _leaf():
            return "done"

        class _Workflow(Workflow):
            async def run(self):
                await self.run_async_step(_leaf())
                self.record.ok = True

        workflow = _Workflow()
        await workflow()

        assert workflow.record.steps[0].parent_id == workflow.record.id


class TestFlatten:
    def test_every_envelope_appears_once(self):
        names = [op.name for op in _tree().flatten()]

        assert sorted(names) == ["a", "a1", "a2", "b", "root"]

    def test_depth_first_parent_before_child(self):
        assert [op.name for op in _tree().flatten()] == ["root", "a", "a1", "a2", "b"]

    def test_a_leaf_flattens_to_itself(self):
        leaf = _op("leaf")

        assert leaf.flatten() == [leaf]

    def test_in_memory_entries_are_references_not_copies(self):
        """Documented, and load-bearing: mutating a returned envelope mutates
        the tree it came from."""
        root = _tree()
        flat = root.flatten()

        assert flat[0] is root
        assert flat[1] is root.steps[0]

    def test_the_nesting_is_rebuildable_from_the_list_alone(self):
        """The point of the exercise — a span list that needs no reference to
        the tree to be re-nested."""
        flat = _tree().flatten()
        by_id = {op.id: op for op in flat}

        children = {}
        for op in flat:
            if op.parent_id:
                children.setdefault(by_id[op.parent_id].name, []).append(op.name)

        assert children == {"root": ["a", "b"], "a": ["a1", "a2"]}


class TestReloadedRecords:
    """`steps: list[Any]` does not re-validate, so a record read back from the
    DB has children that are plain dicts. Flatten has to cope — reading stored
    runs is most of what this is for."""

    def test_a_reloaded_record_still_flattens(self):
        reloaded = WorkFlowOperationResult.model_validate_json(
            _tree().model_dump_json()
        )

        assert isinstance(reloaded.steps[0], dict)
        assert [op.name for op in reloaded.flatten()] == [
            "root",
            "a",
            "a1",
            "a2",
            "b",
        ]

    def test_parent_ids_survive_the_round_trip(self):
        """Because the stamp is part of the record, not derived while
        flattening — a reader that only ever sees the stored tree gets it."""
        reloaded = WorkFlowOperationResult.model_validate_json(
            _tree().model_dump_json()
        )
        flat = reloaded.flatten()

        assert flat[0].parent_id is None
        assert all(op.parent_id for op in flat[1:])

    def test_a_hand_built_record_with_a_junk_step_does_not_break_the_walk(self):
        record = _op("root")
        record.steps.append("not an envelope")

        assert [op.name for op in record.flatten()] == ["root"]


class TestSpanTableUse:
    async def test_each_span_carries_its_own_interval(self):
        """flatten + end_time is the pair a timeline needs: every entry knows
        when it began and ended, and who it ran under."""

        @task(log_info=False)
        async def _leaf():
            await asyncio.sleep(0.01)
            return "done"

        class _Workflow(Workflow):
            async def run(self):
                await self.run_async_step(_leaf())
                self.record.ok = True

        workflow = _Workflow()
        await workflow()
        spans = workflow.record.flatten()

        assert len(spans) == 2
        assert all(span.timing.start_time and span.end_time for span in spans)

    def test_dropping_steps_gives_a_flat_row_per_operation(self):
        """The documented one-liner: without it every row drags its whole
        subtree and the list serializes quadratically."""
        rows = [op.model_copy(update={"steps": []}) for op in _tree().flatten()]

        assert len(rows) == 5
        assert all(row.steps == [] for row in rows)
        assert [row.parent_id for row in rows].count(None) == 1
