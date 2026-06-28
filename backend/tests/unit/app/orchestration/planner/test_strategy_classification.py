"""Tests for StrategyClassificationWorkflow pure logic methods."""
from app.domains.base_request import AnalyzeBaseRequest
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas.request_schemas import (
    FindByTitleRetrieval,
    RecommendationStrategy,
)
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import SystemGoal
from app.domains.registry import BOOK_RETRIEVAL_CLASSES

# strategy_wf fixture comes from tests/unit/app/orchestration/planner/conftest.py


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


class TestExecutionOrder:
    def test_single_retrieval(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf.create_execution_order()
        assert strategy_wf.output.execution_order == [r.id]

    def test_simple_chain(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf.output.accepted = [r, a]
        strategy_wf.create_execution_order()
        assert strategy_wf.output.execution_order == [r.id, a.id]

    def test_parallel_retrievals(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        strategy_wf.output.accepted = [r1, r2]
        strategy_wf.create_execution_order()
        assert set(strategy_wf.output.execution_order) == {r1.id, r2.id}

    def test_fan_in_respects_dependency_order(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        a = _make_analyze("task_3", depends_on_ids=["task_1", "task_2"])
        strategy_wf.output.accepted = [r1, r2, a]
        strategy_wf.create_execution_order()
        order = strategy_wf.output.execution_order
        assert order.index(r1.id) < order.index(a.id)
        assert order.index(r2.id) < order.index(a.id)


class TestCycleDetection:
    def test_cycle_produces_empty_execution_order(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf.output.accepted = [a, b]
        strategy_wf.create_execution_order()
        assert strategy_wf.output.execution_order == []

    def test_cycle_moves_nodes_to_refused(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf.output.accepted = [a, b]
        strategy_wf.create_execution_order()
        assert len(strategy_wf.output.refused) == 2
        assert len(strategy_wf.output.accepted) == 0
        assert a._refusal is True
        assert b._refusal is True


class TestProcessClassificationResult:
    def test_good_strategy_goes_to_accepted(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id)
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.accepted) == 1
        assert len(strategy_wf.output.refused) == 0

    def test_low_confidence_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id)
        r.confidence = 0.3
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.refused) == 1
        assert len(strategy_wf.output.accepted) == 0

    def test_missing_target_goal_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id="goal_ffffffff")
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.refused) == 1


class TestSetLlmId:
    def test_replaces_id_with_internal_format(self, strategy_wf):
        r = _make_retrieval("task_1")
        original_llm_id = r.id
        mapping = strategy_wf.set_llm_id([r])
        assert r.id != original_llm_id
        assert mapping[original_llm_id] == r.id
        assert r._llm_id == original_llm_id

    def test_returns_complete_mapping(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="A")
        r2 = _make_retrieval("task_2", title="B")
        assert len(strategy_wf.set_llm_id([r1, r2])) == 2


class TestMapDependencies:
    def test_translates_llm_ids_to_internal(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        llm_to_internal = strategy_wf.set_llm_id([r, a])
        strategy_wf.map_dependencies_to_internal_ids([r, a], llm_to_internal)
        for dep in a.depends_on:
            assert dep in llm_to_internal.values()

    def test_flags_refusal_on_missing_dep(self, strategy_wf):
        a = _make_analyze("task_2", depends_on_ids=["task_99"])
        strategy_wf.map_dependencies_to_internal_ids([a], {})
        assert a._refusal is True


class TestInjectBookRequestClasses:
    def test_injects_retrieval_when_only_analyze_present(self, strategy_wf):
        request_classes = {RecommendationStrategy}
        strategy_wf._inject_book_request_classes(request_classes)
        for cls in BOOK_RETRIEVAL_CLASSES:
            assert cls in request_classes

    def test_no_injection_when_retrieval_already_present(self, strategy_wf):
        request_classes = {RecommendationStrategy, FindByTitleRetrieval}
        original_size = len(request_classes)
        strategy_wf._inject_book_request_classes(request_classes)
        assert len(request_classes) == original_size

    def test_no_injection_when_only_retrieval_present(self, strategy_wf):
        request_classes = {FindByTitleRetrieval}
        strategy_wf._inject_book_request_classes(request_classes)
        assert request_classes == {FindByTitleRetrieval}
