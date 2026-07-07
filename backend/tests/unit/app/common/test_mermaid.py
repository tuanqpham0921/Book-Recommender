"""Tests for app/common/mermaid.py diagram generation."""

from app.common.mermaid import clean_string_mermaid, mermaid_id, get_mermaid_diagram
from app.domains.base_request import AnalyzeBaseRequest
from app.domains.books.schemas.request_schemas import FindByTitleRetrieval
from app.domains.node_types import UnknownNodeTypeEnum


class _FakeAnalyze(AnalyzeBaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _make_retrieval(id_str="task_1", title="Test Book", goal_id="goal_a1b2c3d4"):
    return FindByTitleRetrieval(
        id=id_str,
        title=title,
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )


def _make_analyze(id_str, depends_on_ids, goal_id="goal_a1b2c3d4"):
    return _FakeAnalyze(
        id=id_str,
        depends_on=depends_on_ids,
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
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
