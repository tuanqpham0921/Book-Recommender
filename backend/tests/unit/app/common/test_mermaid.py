"""Tests for app/common/mermaid.py diagram generation."""
from app.common.mermaid import (
    clean_string_mermaid,
    mermaid_id,
    get_mermaid_diagram,
)
from app.domains.books.schemas.request_schemas import (
    FindByTitleRetrieval,
    RecommendationStrategy,
)
from app.domains.base_request import AnalyzeBaseRequest
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


# ---------------------------------------------------------------------------
# clean_string_mermaid
# ---------------------------------------------------------------------------

def test_clean_string_removes_special_chars():
    raw = 'Hello (world) "test" [bracket] {brace} <angle>'
    result = clean_string_mermaid(raw)
    assert "(" not in result
    assert ")" not in result
    assert '"' not in result
    assert "[" not in result
    assert "{" not in result
    assert "<" not in result


def test_clean_string_preserves_alphanumeric():
    result = clean_string_mermaid("Hello World 123")
    assert "Hello" in result
    assert "World" in result
    assert "123" in result


def test_clean_string_empty_stays_empty():
    assert clean_string_mermaid("") == ""


# ---------------------------------------------------------------------------
# mermaid_id
# ---------------------------------------------------------------------------

def test_mermaid_id_replaces_hyphens():
    assert "-" not in mermaid_id("task-abc")


def test_mermaid_id_keeps_underscores_and_alphanum():
    result = mermaid_id("task_a1b2c3d4")
    assert result == "task_a1b2c3d4"


def test_mermaid_id_replaces_dots():
    assert "." not in mermaid_id("task.1")


# ---------------------------------------------------------------------------
# get_mermaid_diagram
# ---------------------------------------------------------------------------

def test_diagram_starts_with_flowchart_header():
    r = _make_retrieval("task_1")
    diagram = get_mermaid_diagram([r.id], {r.id: r})
    assert diagram.startswith("flowchart LR")


def test_diagram_includes_node_for_each_task():
    r1 = _make_retrieval("task_1", title="Book A")
    r2 = _make_retrieval("task_2", title="Book B")
    diagram = get_mermaid_diagram([r1.id, r2.id], {r1.id: r1, r2.id: r2})
    assert mermaid_id(r1.id) in diagram
    assert mermaid_id(r2.id) in diagram


def test_diagram_includes_edge_for_dependency():
    r = _make_retrieval("task_1")
    a = _make_analyze("task_2", depends_on_ids=["task_1"])
    execution_order = [r.id, a.id]
    id_to_node = {r.id: r, a.id: a}
    diagram = get_mermaid_diagram(execution_order, id_to_node)
    edge = f"{mermaid_id(r.id)} --> {mermaid_id(a.id)}"
    assert edge in diagram


def test_diagram_no_edges_for_independent_tasks():
    r1 = _make_retrieval("task_1", title="Book A")
    r2 = _make_retrieval("task_2", title="Book B")
    diagram = get_mermaid_diagram([r1.id, r2.id], {r1.id: r1, r2.id: r2})
    assert "-->" not in diagram
