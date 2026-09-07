"""Tests for planjane/dial/mermaid.py — goals turned into diagram boxes.

Scoped to what this layer decides: which field heads a box, which fields earn
a row, and the `depends_on` → `sent_to` inversion. Markup, orientation and
emission belong to dial/format.py and are tested in test_mermaid_format.py.

The node types below are arbitrary — any *registered* one works, and the
renderer never asks what a node does. They have to be registered only because
`SystemGoal.target_node_type` is a `NodeTypeEnum`, so parking a node breaks
every test naming it.
"""

from app.domains.planjane.dial import get_goals_mermaid_diagram
from app.domains.planjane.dial.format import mermaid_id
from app.domains.planjane.dial.mermaid import ANSWER_BOX_TITLE, ANSWER_ID_PREFIX
from app.domains.planjane import SystemGoal


def _make_goal(id_str, target_node_type, depends_on=None, description="A goal description"):
    return SystemGoal(
        id=id_str,
        description=description,
        reasoning="A sufficiently long reasoning",
        confidence=1.0,
        target_node_type=target_node_type,
        depends_on=depends_on or [],
    )


def _edges(diagram):
    return sorted(line.strip() for line in diagram.splitlines() if "-->" in line)


def _goal_edges(diagram):
    """Edges between goals only.

    Every sink also draws one into the answer box the task runner will attach
    there; that is `TestAnswerBoxes`' subject, not this layer's inversion.
    """
    return [edge for edge in _edges(diagram) if ANSWER_ID_PREFIX not in edge]


def _answer_ids(diagram):
    return sorted(
        line.strip().split("[")[0]
        for line in diagram.splitlines()
        if line.strip().startswith(ANSWER_ID_PREFIX)
    )


class TestGoalsDiagram:
    def test_empty_goals_returns_none(self):
        assert get_goals_mermaid_diagram([]) is None

    def test_single_goal_has_no_goal_edges(self):
        diagram = get_goals_mermaid_diagram([_make_goal("1", "Retrieve_by_Title")])

        assert diagram.startswith("flowchart")
        assert _goal_edges(diagram) == []

    def test_header_is_target_capability_not_node_type(self):
        # boxes are headed by the capability the goal targets, not "system_goal"
        diagram = get_goals_mermaid_diagram([_make_goal("1", "Retrieve_by_Title")])

        assert "Retrieve_by_Title" in diagram
        assert "system_goal" not in diagram

    def test_box_carries_the_goal_description_and_reasoning(self):
        diagram = get_goals_mermaid_diagram(
            [_make_goal("1", "Retrieve_by_Title", description="Find Dune")]
        )

        assert "Find Dune" in diagram
        assert "A sufficiently long reasoning" in diagram

    def test_depends_on_is_inverted_into_the_arrow_direction(self):
        # goal 3 depends on 1 and 2, so the arrows must point *into* 3
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Retrieve_by_Title"),
            _make_goal("3", "Retrieve_by_Lexical_Traits", depends_on=["1", "2"]),
        ]
        diagram = get_goals_mermaid_diagram(goals)

        assert _goal_edges(diagram) == [
            f"{mermaid_id('1')} --> {mermaid_id('3')}",
            f"{mermaid_id('2')} --> {mermaid_id('3')}",
        ]

    def test_a_dependency_outside_the_plan_draws_no_edge(self):
        # the planner can refuse goal "1" and still accept one that depends on
        # it; drawing that edge would conjure an empty box for a goal that was
        # never planned
        diagram = get_goals_mermaid_diagram(
            [_make_goal("2", "Retrieve_by_Lexical_Traits", depends_on=["refused_1"])]
        )

        assert _goal_edges(diagram) == []
        assert "refused_1" not in diagram

    def test_deep_chain_orients_lr(self):
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Retrieve_by_Lexical_Traits", depends_on=["1"]),
            _make_goal("3", "Retrieve_by_Lexical_Traits", depends_on=["2"]),
        ]

        assert get_goals_mermaid_diagram(goals).startswith("flowchart LR")

    def test_cycle_does_not_recurse_forever(self):
        # invalid plan (execution_order reports it unreachable), but the
        # renderer must not hang
        goals = [
            _make_goal("1", "Retrieve_by_Title", depends_on=["2"]),
            _make_goal("2", "Retrieve_by_Title", depends_on=["1"]),
        ]

        assert get_goals_mermaid_diagram(goals).startswith("flowchart")


class TestAnswerBoxes:
    """The answer stage is drawn, though the planner never chose it.

    One box per sink, because the task runner attaches one answer per sink —
    the diagram and the runner have to agree about where a reply comes from,
    and this is the half the user sees before anything runs.
    """

    def test_a_lone_goal_is_its_own_sink_and_gains_one_answer(self):
        diagram = get_goals_mermaid_diagram([_make_goal("1", "Retrieve_by_Title")])

        assert _answer_ids(diagram) == [f"{ANSWER_ID_PREFIX}1"]
        assert ANSWER_BOX_TITLE in diagram
        assert _edges(diagram) == [f"{mermaid_id('1')} --> {ANSWER_ID_PREFIX}1"]

    def test_only_the_sink_gains_one(self):
        # a chained ask — "do you have Dune? and recommend like it" — is one
        # branch with one reply, written from both goals
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Analyze_Similar_Books", depends_on=["1"]),
        ]
        diagram = get_goals_mermaid_diagram(goals)

        assert _answer_ids(diagram) == [f"{ANSWER_ID_PREFIX}1"]
        assert f"{mermaid_id('2')} --> {ANSWER_ID_PREFIX}1" in _edges(diagram)

    def test_each_independent_branch_gains_its_own(self):
        # a compound ask — two disjoint intents, so two replies
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Retrieve_by_Author"),
            _make_goal("3", "Combine_Intersect", depends_on=["1", "2"]),
            _make_goal("4", "Retrieve_by_Title"),
            _make_goal("5", "Analyze_Similar_Books", depends_on=["4"]),
        ]
        diagram = get_goals_mermaid_diagram(goals)

        assert _answer_ids(diagram) == [
            f"{ANSWER_ID_PREFIX}1",
            f"{ANSWER_ID_PREFIX}2",
        ]
        edges = _edges(diagram)
        assert f"{mermaid_id('3')} --> {ANSWER_ID_PREFIX}1" in edges
        assert f"{mermaid_id('5')} --> {ANSWER_ID_PREFIX}2" in edges

    def test_a_cycle_hangs_no_answer_off_anything(self):
        # every box points somewhere, so there is no end to attach a reply to
        goals = [
            _make_goal("1", "Retrieve_by_Title", depends_on=["2"]),
            _make_goal("2", "Retrieve_by_Title", depends_on=["1"]),
        ]

        assert _answer_ids(get_goals_mermaid_diagram(goals)) == []
