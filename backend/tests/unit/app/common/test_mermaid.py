"""Tests for app/common/mermaid.py diagram generation."""

from app.common.mermaid import (
    choose_orientation,
    clean_string_mermaid,
    mermaid_id,
    get_mermaid_diagram,
    get_goals_mermaid_diagram,
    get_parsed_mermaid_diagram,
)
from app.domains.base_request import BaseRequest
from app.domains.books.find_by_title import FindByTitleRetrieval
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import SystemGoal


def _make_goal(id_str, target_node_type, depends_on=None, description="A goal description"):
    return SystemGoal(
        id=id_str,
        description=description,
        reasoning="A sufficiently long reasoning",
        confidence=1.0,
        target_node_type=target_node_type,
        depends_on=depends_on or [],
    )


class _FakeAnalyze(BaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _stamp(request, id_str, depends_on_ids=None):
    """Apply the plan id / dependencies the way the planner does — they are
    private attrs, not fields, so they cannot be passed to the constructor."""
    request._id = id_str
    request._depends_on = list(depends_on_ids or [])
    return request


def _make_retrieval(id_str="task_1", title="Test Book"):
    return _stamp(
        FindByTitleRetrieval(
            title=title,
            reasoning="A sufficiently long reasoning for the test",
            confidence=0.9,
        ),
        id_str,
    )


def _make_analyze(id_str, depends_on_ids):
    return _stamp(
        _FakeAnalyze(
            reasoning="A sufficiently long reasoning for the test",
            confidence=0.9,
        ),
        id_str,
        depends_on_ids,
    )


class TestCleanStringMermaid:
    def test_removes_special_chars(self):
        raw = 'Hello (world) "test" [bracket] {brace} <angle>'
        result = clean_string_mermaid(raw)
        for char in '()"[]{}<>':
            assert char not in result

    def test_preserves_alphanumeric(self):
        result = clean_string_mermaid("Hello World 123")
        assert "Hello" in result
        assert "World" in result
        assert "123" in result

    def test_empty_string_stays_empty(self):
        assert clean_string_mermaid("") == ""


class TestMermaidId:
    def test_replaces_hyphens(self):
        assert "-" not in mermaid_id("task-abc")

    def test_keeps_underscores_and_alphanum(self):
        assert mermaid_id("task_a1b2c3d4") == "task_a1b2c3d4"

    def test_replaces_dots(self):
        assert "." not in mermaid_id("task.1")


class TestGetMermaidDiagram:
    def test_starts_with_flowchart_header(self):
        r = _make_retrieval("task_1")
        assert get_mermaid_diagram([r.id], {r.id: r}).startswith("flowchart TD")

    def test_includes_node_for_each_task(self):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        diagram = get_mermaid_diagram([r1.id, r2.id], {r1.id: r1, r2.id: r2})
        assert mermaid_id(r1.id) in diagram
        assert mermaid_id(r2.id) in diagram

    def test_includes_edge_for_dependency(self):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        diagram = get_mermaid_diagram([r.id, a.id], {r.id: r, a.id: a})
        assert f"{mermaid_id(r.id)} --> {mermaid_id(a.id)}" in diagram

    def test_no_edges_for_independent_tasks(self):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        diagram = get_mermaid_diagram([r1.id, r2.id], {r1.id: r1, r2.id: r2})
        assert "-->" not in diagram

    def test_uses_orientation_from_levels(self):
        r = _make_retrieval("task_1")
        a1 = _make_analyze("task_2", depends_on_ids=["task_1"])
        a2 = _make_analyze("task_3", depends_on_ids=["task_2"])
        levels = {"task_1": 0, "task_2": 1, "task_3": 2}
        diagram = get_mermaid_diagram(
            ["task_1", "task_2", "task_3"],
            {"task_1": r, "task_2": a1, "task_3": a2},
            levels,
        )
        assert diagram.startswith("flowchart LR")


class TestGetGoalsMermaidDiagram:
    def test_empty_goals_returns_none(self):
        assert get_goals_mermaid_diagram([]) is None

    def test_single_goal_has_no_edges(self):
        g = _make_goal("1", "Retrieve_by_Title")
        diagram = get_goals_mermaid_diagram([g])
        assert diagram.startswith("flowchart")
        assert "-->" not in diagram

    def test_header_is_target_capability_not_node_type(self):
        # boxes are headed by the capability the goal targets, not "system_goal"
        g = _make_goal("1", "Retrieve_by_Title")
        diagram = get_goals_mermaid_diagram([g])
        assert "Retrieve_by_Title" in diagram
        assert "system_goal" not in diagram

    def test_edges_drawn_from_depends_on(self):
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Retrieve_by_Title"),
            _make_goal("3", "Analyze_Recommend", depends_on=["1", "2"]),
        ]
        diagram = get_goals_mermaid_diagram(goals)
        assert f"{mermaid_id('1')} --> {mermaid_id('3')}" in diagram
        assert f"{mermaid_id('2')} --> {mermaid_id('3')}" in diagram

    def test_deep_chain_orients_lr(self):
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Analyze_Recommend", depends_on=["1"]),
            _make_goal("3", "Analyze_Recommend", depends_on=["2"]),
        ]
        assert get_goals_mermaid_diagram(goals).startswith("flowchart LR")

    def test_cycle_does_not_recurse_forever(self):
        # invalid plan (planner should reject), but the renderer must not hang
        goals = [
            _make_goal("1", "Retrieve_by_Title", depends_on=["2"]),
            _make_goal("2", "Retrieve_by_Title", depends_on=["1"]),
        ]
        diagram = get_goals_mermaid_diagram(goals)
        assert diagram.startswith("flowchart")


class TestGetParsedMermaidDiagram:
    def test_empty_requests_returns_none(self):
        assert get_parsed_mermaid_diagram([]) is None

    def test_unstamped_requests_are_dropped(self):
        # no _id means no place in the graph
        r = FindByTitleRetrieval(
            title="Dune",
            reasoning="A sufficiently long reasoning for the test",
            confidence=0.9,
        )
        assert get_parsed_mermaid_diagram([r]) is None

    def test_box_shows_parsed_arguments(self):
        r = _make_retrieval("1", title="Dune")
        diagram = get_parsed_mermaid_diagram([r])
        assert "Retrieve_by_Title" in diagram
        assert "Dune" in diagram

    def test_private_attrs_not_leaked_into_label(self):
        diagram = get_parsed_mermaid_diagram([_make_retrieval("1")])
        assert "_refusal" not in diagram
        assert "_depends_on" not in diagram

    def test_edges_drawn_from_depends_on(self):
        requests = [
            _make_retrieval("1", title="Book A"),
            _make_retrieval("2", title="Book B"),
            _make_analyze("3", depends_on_ids=["1", "2"]),
        ]
        diagram = get_parsed_mermaid_diagram(requests)
        assert f"{mermaid_id('1')} --> {mermaid_id('3')}" in diagram
        assert f"{mermaid_id('2')} --> {mermaid_id('3')}" in diagram

    def test_same_shape_as_goal_diagram(self):
        # the whole point: parsed requests inherit their goal's id/depends_on,
        # so the two diagrams differ in box contents but never in topology
        goals = [
            _make_goal("1", "Retrieve_by_Title"),
            _make_goal("2", "Analyze_Recommend", depends_on=["1"]),
        ]
        requests = [
            _make_retrieval("1"),
            _make_analyze("2", depends_on_ids=["1"]),
        ]

        def _edges(diagram):
            return sorted(
                line.strip() for line in diagram.splitlines() if "-->" in line
            )

        goal_diagram = get_goals_mermaid_diagram(goals)
        parsed_diagram = get_parsed_mermaid_diagram(requests)
        assert _edges(parsed_diagram) == _edges(goal_diagram)
        assert parsed_diagram.splitlines()[0] == goal_diagram.splitlines()[0]

    def test_cycle_does_not_recurse_forever(self):
        requests = [
            _make_analyze("1", depends_on_ids=["2"]),
            _make_analyze("2", depends_on_ids=["1"]),
        ]
        assert get_parsed_mermaid_diagram(requests).startswith("flowchart")


class TestChooseOrientation:
    def test_no_levels_defaults_to_td(self):
        assert choose_orientation(None) == "TD"
        assert choose_orientation({}) == "TD"

    def test_wide_shallow_graph_is_td(self):
        # 3 nodes at level 0 (width 3), 1 level deep -> concurrency-heavy
        levels = {"a": 0, "b": 0, "c": 0}
        assert choose_orientation(levels) == "TD"

    def test_narrow_deep_graph_is_lr(self):
        # 1 node per level across 3 levels -> sequential-heavy
        levels = {"a": 0, "b": 1, "c": 2}
        assert choose_orientation(levels) == "LR"

    def test_tie_favors_td(self):
        levels = {"a": 0}
        assert choose_orientation(levels) == "TD"
