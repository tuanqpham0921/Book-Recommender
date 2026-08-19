"""`flatten()` and `parent_id` — the trace tree as a span list.

The two go together: flattening is only useful if the nesting survives it, and
what makes it survive is `add_step` stamping `parent_id` when it attaches a
child. That stamp is asserted here rather than in the attach tests because it
exists *for* this — a flat list whose entries can be re-nested from their own
fields, with no reference to the tree they came from.

The other half is the shape: every entry comes back with an empty `steps`, so
no row in the list drags a subtree along with it. With one envelope class that
is a property of the row rather than of its type — `to_span()` is what enforces
it.
"""

import asyncio

from airglider import OperationResult, Workflow, task


def _op(name: str) -> OperationResult:
    return OperationResult(name=name, ok=True)


def _name(op: OperationResult) -> str:
    """`name` is optional on the model but set on every envelope built here.
    The placeholder keeps names sortable and dict-keyable, and still fails the
    assert loudly if one ever goes missing."""
    return op.name or "<unnamed>"


def _tree() -> OperationResult:
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

    def test_add_step_takes_a_leaf_envelope_too(self):
        """A step is a step whether a `@task` or a `Workflow` produced it —
        which is why `add_step` checks against the base class."""
        parent, leaf = _op("parent"), OperationResult(name="leaf", ok=True)
        parent.add_step(leaf)

        assert leaf.parent_id == parent.id
        assert parent.steps == [leaf]

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
                await _leaf()
                self.record.ok = True

        workflow = _Workflow()
        await workflow()

        assert workflow.record.steps[0].parent_id == workflow.record.id


class TestToSpan:
    def test_a_leaf_is_already_a_span(self):
        leaf = OperationResult(name="leaf", ok=True)

        assert leaf.to_span() is leaf

    def test_a_node_with_children_projects_down_to_a_childless_copy(self):
        """With one envelope class, "childless" is an empty `steps` rather than
        a missing field — and it must be a copy, or emptying it would strip the
        children off the tree the span was taken from."""
        tree = _tree()
        span = tree.to_span()

        assert span is not tree
        assert span.steps == []
        assert len(tree.steps) == 2

    def test_the_projection_keeps_every_other_field(self):
        node = _op("node")
        node.parent_id = "op_parent"
        node.timing.duration = 1.5
        node.input = {"query": "q"}
        span = node.to_span()

        assert span.id == node.id
        assert span.parent_id == "op_parent"
        assert span.name == "node"
        assert span.ok is True
        assert span.duration == 1.5
        assert span.input == {"query": "q"}

    def test_the_payload_is_not_dumped_into_a_dict(self):
        """`model_construct` rather than dump-and-revalidate: a live payload
        stays the object the executor produced."""

        class _Payload:
            pass

        payload = _Payload()
        node = _op("node")
        node.response.result = payload

        assert node.to_span().result is payload


class TestFlatten:
    def test_every_envelope_appears_once(self):
        names = [_name(op) for op in _tree().flatten()]

        assert sorted(names) == ["a", "a1", "a2", "b", "root"]

    def test_depth_first_parent_before_child(self):
        assert [op.name for op in _tree().flatten()] == ["root", "a", "a1", "a2", "b"]

    def test_a_childless_node_flattens_to_one_span(self):
        assert [op.name for op in _op("node").flatten()] == ["node"]

    def test_no_entry_carries_a_subtree(self):
        """The point of projecting: a row that kept its own children would
        serialize the whole tree once per level."""
        tree = _tree()
        flat = tree.flatten()

        assert all(type(op) is OperationResult for op in flat)
        assert all(op.steps == [] for op in flat)
        # the tree itself is untouched — the rows are views, not surgery on it
        assert len(tree.steps) == 2

    def test_a_leaf_step_comes_back_by_reference(self):
        """It has no subtree to drop, so there is nothing to copy."""
        root = _op("root")
        leaf = OperationResult(name="leaf", ok=True)
        root.add_step(leaf)

        assert root.flatten()[1] is leaf

    def test_the_nesting_is_rebuildable_from_the_list_alone(self):
        """The point of the exercise — a span list that needs no reference to
        the tree to be re-nested."""
        flat = _tree().flatten()
        by_id = {op.id: op for op in flat}

        children: dict[str, list[str]] = {}
        for op in flat:
            if op.parent_id:
                children.setdefault(_name(by_id[op.parent_id]), []).append(_name(op))

        assert children == {"root": ["a", "b"], "a": ["a1", "a2"]}


class TestReloadedRecords:
    """`steps: list[Any]` does not re-validate, so a record read back from the
    DB has children that are plain dicts. Flatten has to cope — reading stored
    runs is most of what this is for."""

    def test_a_reloaded_record_still_flattens(self):
        reloaded = OperationResult.model_validate_json(_tree().model_dump_json())

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
        reloaded = OperationResult.model_validate_json(_tree().model_dump_json())
        flat = reloaded.flatten()

        assert flat[0].parent_id is None
        assert all(op.parent_id for op in flat[1:])

    def test_a_reloaded_leaf_step_is_not_dropped(self):
        """A step dict is validated back into an envelope on the way past, so a
        childless `@task` record survives the round trip."""
        root = _op("root")
        root.add_step(OperationResult(name="leaf", ok=True))
        reloaded = OperationResult.model_validate_json(root.model_dump_json())

        assert [op.name for op in reloaded.flatten()] == ["root", "leaf"]

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
                await _leaf()
                self.record.ok = True

        workflow = _Workflow()
        await workflow()
        spans = workflow.record.flatten()

        assert len(spans) == 2
        assert all(span.timing.start_time and span.end_time for span in spans)

    def test_the_list_serializes_without_repeating_the_tree(self):
        """One row, one operation. With subtrees left in, "root" alone would
        re-encode all five."""
        flat = _tree().flatten()
        encoded = [op.model_dump_json() for op in flat]

        assert len(flat) == 5
        assert all(encoding.count('"id"') == 1 for encoding in encoded)
