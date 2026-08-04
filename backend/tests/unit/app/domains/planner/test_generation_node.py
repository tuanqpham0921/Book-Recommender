"""Tests for the terminal answer stage attached to every plan.

The whole file is really one assertion in several shapes: "end of the DAG" means
*sink* (nothing depends on it), not *deepest* and not *most dependencies*. The
first two tests are the concrete plans an earlier level-bucketing cut got wrong.
"""

from app.domains.planner.generation_node import (
    GenerationNode,
    GenerationTypeEnum,
    create_generation_nodes,
    find_sink_goals,
)
from app.domains.planner.parse_intent import SystemGoal


def goal(goal_id: str, node_type: str, depends_on: list[str]) -> SystemGoal:
    return SystemGoal(
        id=goal_id,
        description="d",
        reasoning="r",
        confidence=1.0,
        target_node_type=node_type,
        depends_on=depends_on,
    )


def attached_to(nodes: list[GenerationNode]) -> list[list[str]]:
    return [node.depends_on for node in nodes]


class TestFindSinkGoals:
    def test_the_node_with_the_most_dependencies_is_not_the_end(self):
        # base case 46: four retrievals -> Compare -> Recommend. The middle
        # node has four deps and the last has one, so counting deps picks the
        # middle — which would write the answer from the comparison and
        # silently drop the recommendation the user actually asked for.
        # (Analyze_Compare is parked, so goal 5 stands in for it; only the
        # shape matters here.)
        plan = [
            goal("1", "Retrieve_by_Title", []),
            goal("2", "Retrieve_by_Title", []),
            goal("3", "Retrieve_by_Title", []),
            goal("4", "Retrieve_by_Title", []),
            goal("5", "Analyze_Recommend", ["1", "2", "3", "4"]),
            goal("6", "Analyze_Recommend", ["5"]),
        ]

        assert [g.id for g in find_sink_goals(plan)] == ["6"]

    def test_an_independent_goal_is_its_own_end(self):
        # base case 45: an out-of-domain goal runs alongside retrieve ->
        # recommend. Goal 1 has no deps and no dependents, so a depth- or
        # count-based rule buries it with the retrievals and never answers it.
        plan = [
            goal("1", "unknown", []),
            goal("2", "Retrieve_by_Title", []),
            goal("3", "Analyze_Recommend", ["2"]),
        ]

        assert [g.id for g in find_sink_goals(plan)] == ["1", "3"]

    def test_a_single_goal_plan_is_all_sink(self):
        assert [g.id for g in find_sink_goals([goal("1", "Retrieve_by_Title", [])])] == ["1"]

    def test_no_goals_no_sinks(self):
        assert find_sink_goals([]) == []


class TestCreateGenerationNodes:
    def test_one_answer_per_sink(self):
        plan = [
            goal("1", "unknown", []),
            goal("2", "Retrieve_by_Title", []),
            goal("3", "Analyze_Recommend", ["2"]),
        ]

        assert attached_to(create_generation_nodes(plan)) == [["1"], ["3"]]

    def test_ids_are_unique_so_the_graph_does_not_collapse(self):
        # two nodes under one id would overwrite each other in the diagram's
        # id-keyed mapping, silently losing an answer
        plan = [goal("1", "Retrieve_by_Title", []), goal("2", "Retrieve_by_Title", [])]

        ids = [node.id for node in create_generation_nodes(plan)]

        assert len(set(ids)) == len(ids) == 2

    def test_single_answer_collapses_every_sink_onto_one_node(self):
        plan = [
            goal("1", "unknown", []),
            goal("2", "Retrieve_by_Title", []),
            goal("3", "Analyze_Recommend", ["2"]),
        ]

        nodes = create_generation_nodes(plan, single_answer=True)

        assert len(nodes) == 1
        assert nodes[0].depends_on == ["1", "3"]

    def test_empty_plan_gets_no_answer_node(self):
        # and specifically does not raise — the old max() over an empty level
        # map was a latent ValueError guarded only by the caller's early return
        assert create_generation_nodes([]) == []

    def test_a_cycle_still_produces_an_answer(self):
        # every goal is depended on, so there is no sink. The plan is invalid,
        # but returning [] would leave the user with no reply at all.
        plan = [
            goal("1", "Retrieve_by_Title", ["2"]),
            goal("2", "Analyze_Recommend", ["1"]),
        ]

        assert attached_to(create_generation_nodes(plan)) == [["1"], ["2"]]

    def test_defaults_to_the_generic_answer_type(self):
        nodes = create_generation_nodes([goal("1", "Retrieve_by_Title", [])])

        assert nodes[0].node_type is GenerationTypeEnum.GENERIC_RESPONSE

    def test_depends_on_is_a_list_not_a_string(self):
        # the renderer iterates depends_on; a bare str would yield one edge per
        # character rather than one edge to the goal
        node = create_generation_nodes([goal("12", "Retrieve_by_Title", [])])[0]

        assert node.depends_on == ["12"]
        assert node.get_depends_on() == ["12"]
