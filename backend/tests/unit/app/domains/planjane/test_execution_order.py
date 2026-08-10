"""Tests for PlanJaneOutput.execution_order — the dependency layering.

`TaskRunnerWorkflow` runs the layers flattened, so today only the flattened
order has to be a valid topological order. The layering is asserted anyway
because layers are the parallelization seam: the moment a layer is run with
`asyncio.gather`, a goal sharing a layer with its own dependency becomes a
race. The previous implementation produced exactly that.
"""

import pytest

from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.planjane import PlanJaneOutput
from app.domains.planjane.schemas import SystemGoal


def goal(goal_id: str, depends_on: list[str] | None = None) -> SystemGoal:
    return SystemGoal(
        id=goal_id,
        description="Find a book about machine learning topics",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
        target_node_type=FindTitleNodeTypeEnum.REQUEST,
        depends_on=depends_on or [],
    )


def order_of(*goals: SystemGoal):
    """(layers as id lists, unreachable as ids)."""
    result = PlanJaneOutput(accepted_goals=list(goals)).execution_order()
    return (
        [[g.id for g in layer] for layer in result.layers],
        [g.id for g in result.unreachable],
    )


class TestLayering:
    def test_independent_goals_share_one_layer(self):
        layers, unreachable = order_of(goal("a"), goal("b"))

        assert layers == [["a", "b"]]
        assert unreachable == []

    def test_a_dependent_goal_lands_in_a_later_layer_than_its_dependency(self):
        # the core regression: "c" depends on "b" and must not share its layer
        layers, _ = order_of(goal("a"), goal("b"), goal("c", ["b"]))

        assert layers == [["a", "b"], ["c"]]

    def test_layering_is_independent_of_the_order_goals_are_listed_in(self):
        # the planner emits goals in whatever order it likes; a dependent
        # listed before its dependency used to invert the layers
        assert order_of(goal("c", ["b"]), goal("b"), goal("a"))[0] == [
            ["b", "a"],
            ["c"],
        ]

    def test_a_chain_produces_one_layer_per_link(self):
        layers, _ = order_of(goal("a"), goal("b", ["a"]), goal("c", ["b"]))

        assert layers == [["a"], ["b"], ["c"]]

    def test_a_diamond_joins_back_into_a_single_layer(self):
        layers, _ = order_of(
            goal("a"), goal("b", ["a"]), goal("c", ["a"]), goal("d", ["b", "c"])
        )

        assert layers == [["a"], ["b", "c"], ["d"]]

    def test_a_goal_naming_the_same_dependency_twice_still_runs(self):
        # both the wait count and the unblocking edges come from the same
        # de-duplicated list; counting one side twice would strand "a"
        layers, unreachable = order_of(goal("b"), goal("a", ["b", "b"]))

        assert layers == [["b"], ["a"]]
        assert unreachable == []

    def test_empty_plan_produces_no_layers(self):
        assert order_of() == ([], [])


class TestUnreachableGoals:
    """A goal that can never run is *returned*, never dropped — silently
    omitting it is how a user asks for three things, gets one, and is told
    the turn succeeded."""

    def test_a_dependency_cycle_is_reported_not_dropped(self):
        layers, unreachable = order_of(goal("a", ["b"]), goal("b", ["a"]))

        assert layers == []
        assert unreachable == ["a", "b"]

    def test_a_goal_depending_on_a_refused_goal_is_reported(self):
        # accepted_goals is not closed over depends_on: the planner can refuse
        # goal "1" and still accept a goal that depends on it
        layers, unreachable = order_of(goal("b", ["refused_1"]))

        assert layers == []
        assert unreachable == ["b"]

    def test_a_blocked_goal_blocks_its_own_dependents_transitively(self):
        layers, unreachable = order_of(
            goal("a"), goal("b", ["missing"]), goal("c", ["b"])
        )

        assert layers == [["a"]]
        assert unreachable == ["b", "c"]

    def test_a_self_dependency_is_reported_rather_than_deadlocking(self):
        layers, unreachable = order_of(goal("a", ["a"]))

        assert layers == []
        assert unreachable == ["a"]

    def test_every_accepted_goal_is_either_scheduled_or_unreachable(self):
        # the invariant the task runner's bookkeeping relies on — nothing may
        # fall out of the plan without being accounted for somewhere
        goals = [
            goal("a"),
            goal("b", ["a"]),
            goal("c", ["missing"]),
            goal("d", ["e"]),
            goal("e", ["d"]),
        ]
        result = PlanJaneOutput(accepted_goals=goals).execution_order()

        placed = [g.id for layer in result.layers for g in layer]
        assert sorted(placed + [g.id for g in result.unreachable]) == [
            "a",
            "b",
            "c",
            "d",
            "e",
        ]


class TestFlattenedOrderIsTopological:
    """What TaskRunnerWorkflow actually depends on today: it runs the layers
    flattened, so every goal must appear after all of its dependencies."""

    @pytest.mark.parametrize(
        "goals",
        [
            [goal("a"), goal("b", ["a"]), goal("c", ["b"])],
            [goal("c", ["b"]), goal("b", ["a"]), goal("a")],
            [goal("d", ["b", "c"]), goal("b", ["a"]), goal("c", ["a"]), goal("a")],
        ],
        ids=["chain", "reversed-chain", "diamond-reversed"],
    )
    def test_dependencies_always_come_first(self, goals):
        result = PlanJaneOutput(accepted_goals=goals).execution_order()

        seen: set[str] = set()
        for layer in result.layers:
            for placed in layer:
                assert set(placed.depends_on) <= seen, (
                    f"{placed.id} ran before {set(placed.depends_on) - seen}"
                )
            seen |= {placed.id for placed in layer}
