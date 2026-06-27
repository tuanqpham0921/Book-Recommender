"""Tests for StrategyClassificationWorkflow pure logic methods."""
from unittest.mock import MagicMock

import pytest

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.domains.base_request import AnalyzeBaseRequest, DomainRequest
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas.request_schemas import (
    CompareStrategy,
    FindByTitleRetrieval,
    RecommendationStrategy,
)
from app.domains.node_types import UnknownNodeTypeEnum
from app.orchestration.planner.parse_intent import SystemGoal
from app.orchestration.planner.strategy_classification import (
    StrategyClassificationWorkflow,
)
from app.domains.registry import BOOK_RETRIEVAL_CLASSES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeAnalyze(AnalyzeBaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _make_retrieval(id_str="task_1", goal_id="goal_a1b2c3d4", title="Test Book"):
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


def _make_goal(node_type=BookNodeTypeEnum.FIND_TITLE, goal_id=None):
    g = SystemGoal(
        description="Find a book about machine learning topics",
        confidence=0.9,
        target_node_type=node_type,
    )
    if goal_id:
        g._id = goal_id
    return g


@pytest.fixture
def wf():
    return StrategyClassificationWorkflow(
        sse_stream=SSEStream(),
        user_message=UserMessage(content="test"),
        llm_client=MagicMock(),
    )


# ---------------------------------------------------------------------------
# create_execution_order: basic topological sort
# ---------------------------------------------------------------------------

def test_execution_order_single_retrieval(wf):
    r = _make_retrieval("task_1")
    wf.output.accepted = [r]
    wf.create_execution_order()
    assert wf.output.execution_order == [r.id]


def test_execution_order_simple_chain(wf):
    r = _make_retrieval("task_1")
    a = _make_analyze("task_2", depends_on_ids=["task_1"])
    wf.output.accepted = [r, a]
    wf.create_execution_order()
    assert wf.output.execution_order == [r.id, a.id]


def test_execution_order_parallel_retrievals(wf):
    r1 = _make_retrieval("task_1", title="Book A")
    r2 = _make_retrieval("task_2", title="Book B")
    wf.output.accepted = [r1, r2]
    wf.create_execution_order()
    assert set(wf.output.execution_order) == {r1.id, r2.id}


def test_execution_order_fan_in(wf):
    r1 = _make_retrieval("task_1", title="Book A")
    r2 = _make_retrieval("task_2", title="Book B")
    a = _make_analyze("task_3", depends_on_ids=["task_1", "task_2"])
    wf.output.accepted = [r1, r2, a]
    wf.create_execution_order()
    order = wf.output.execution_order
    assert order.index(r1.id) < order.index(a.id)
    assert order.index(r2.id) < order.index(a.id)


# ---------------------------------------------------------------------------
# create_execution_order: cycle detection
# ---------------------------------------------------------------------------

def test_cycle_produces_empty_execution_order(wf):
    a = _make_analyze("task_1", depends_on_ids=["task_2"])
    b = _make_analyze("task_2", depends_on_ids=["task_1"])
    wf.output.accepted = [a, b]
    wf.create_execution_order()
    assert wf.output.execution_order == []


def test_cycle_moves_nodes_to_refused(wf):
    a = _make_analyze("task_1", depends_on_ids=["task_2"])
    b = _make_analyze("task_2", depends_on_ids=["task_1"])
    wf.output.accepted = [a, b]
    wf.create_execution_order()
    assert len(wf.output.refused) == 2
    assert len(wf.output.accepted) == 0
    assert a._refusal is True
    assert b._refusal is True


# ---------------------------------------------------------------------------
# process_classification_result
# ---------------------------------------------------------------------------

def test_good_strategy_goes_to_accepted(wf):
    goal = _make_goal()
    r = _make_retrieval(id_str="task_1", goal_id=goal.id)
    wf.process_classification_result([r], [goal])
    assert len(wf.output.accepted) == 1
    assert len(wf.output.refused) == 0


def test_low_confidence_strategy_goes_to_refused(wf):
    goal = _make_goal()
    r = _make_retrieval(id_str="task_1", goal_id=goal.id)
    r.confidence = 0.3  # below accepted_tuning=0.7
    wf.process_classification_result([r], [goal])
    assert len(wf.output.refused) == 1
    assert len(wf.output.accepted) == 0


def test_missing_target_goal_goes_to_refused(wf):
    goal = _make_goal()
    r = _make_retrieval(id_str="task_1", goal_id="goal_ffffffff")  # not in system_goals
    wf.process_classification_result([r], [goal])
    assert len(wf.output.refused) == 1


# ---------------------------------------------------------------------------
# set_llm_id
# ---------------------------------------------------------------------------

def test_set_llm_id_replaces_id_with_internal_format(wf):
    r = _make_retrieval("task_1")
    original_llm_id = r.id
    mapping = wf.set_llm_id([r])
    assert r.id != original_llm_id
    assert mapping[original_llm_id] == r.id
    assert r._llm_id == original_llm_id


def test_set_llm_id_returns_complete_mapping(wf):
    r1 = _make_retrieval("task_1", title="A")
    r2 = _make_retrieval("task_2", title="B")
    mapping = wf.set_llm_id([r1, r2])
    assert len(mapping) == 2


# ---------------------------------------------------------------------------
# map_dependencies_to_internal_ids
# ---------------------------------------------------------------------------

def test_map_dependencies_translates_llm_ids(wf):
    r = _make_retrieval("task_1")
    a = _make_analyze("task_2", depends_on_ids=["task_1"])
    llm_to_internal = wf.set_llm_id([r, a])
    wf.map_dependencies_to_internal_ids([r, a], llm_to_internal)
    for dep in a.depends_on:
        assert dep in llm_to_internal.values()


def test_map_dependencies_flags_refusal_on_missing_dep(wf):
    a = _make_analyze("task_2", depends_on_ids=["task_99"])  # unknown dependency
    wf.map_dependencies_to_internal_ids([a], {})
    assert a._refusal is True


# ---------------------------------------------------------------------------
# _inject_book_request_classes
# ---------------------------------------------------------------------------

def test_inject_retrieval_when_only_analyze_present(wf):
    request_classes = {RecommendationStrategy}
    wf._inject_book_request_classes(request_classes)
    for cls in BOOK_RETRIEVAL_CLASSES:
        assert cls in request_classes


def test_no_injection_when_retrieval_already_present(wf):
    request_classes = {RecommendationStrategy, FindByTitleRetrieval}
    original_size = len(request_classes)
    wf._inject_book_request_classes(request_classes)
    assert len(request_classes) == original_size


def test_no_injection_when_only_retrieval_present(wf):
    request_classes = {FindByTitleRetrieval}
    wf._inject_book_request_classes(request_classes)
    assert request_classes == {FindByTitleRetrieval}
