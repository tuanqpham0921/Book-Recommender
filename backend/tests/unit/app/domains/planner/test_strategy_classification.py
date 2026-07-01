"""Tests for StrategyClassificationWorkflow pure logic methods."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.common.messages import UserMessage
from app.domains.base_request import AnalyzeBaseRequest
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas.request_schemas import (
    FindByTitleRetrieval,
    RecommendationStrategy,
)
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import SystemGoal
from app.domains.planner.strategy_classification import MAX_STRATEGIES, StrategyRequest
from app.domains.registry import BOOK_RETRIEVAL_CLASSES

class _FakeAnalyze(AnalyzeBaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _make_retrieval(id_str="task_1", goal_id="goal_a1b2c3d4", title="Test Book", confidence=0.9):
    return FindByTitleRetrieval(
        id=id_str,
        title=title,
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=confidence,
    )


def _make_analyze(id_str, depends_on_ids, goal_id="goal_a1b2c3d4", confidence=0.9):
    return _FakeAnalyze(
        id=id_str,
        depends_on=depends_on_ids,
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=confidence,
    )


def _make_goal(node_type=BookNodeTypeEnum.FIND_TITLE, goal_id=None, confidence=0.9):
    g = SystemGoal(
        description="Find a book about machine learning topics",
        confidence=confidence,
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
        r = _make_retrieval(id_str="task_1", goal_id=goal.id, confidence=0.3)
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.refused) == 1
        assert len(strategy_wf.output.accepted) == 0

    def test_missing_target_goal_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id="goal_ffffffff")
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.refused) == 1

    def test_empty_target_goal_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id)
        r.target_goal = []
        strategy_wf.process_classification_result([r], [goal])
        assert len(strategy_wf.output.refused) == 1


class TestFilterCandidates:
    def test_no_refused_returns_candidates_unchanged(self, strategy_wf):
        r = _make_retrieval("task_1")
        result = strategy_wf._filter_candidates([r], {r.id: r})
        assert result == [r]

    def test_dependent_of_refused_node_is_removed_and_refused(self, strategy_wf):
        goal = _make_goal()
        refused = _make_retrieval("task_1", goal_id=goal.id)
        refused.refuse("low confidence")
        strategy_wf.output.refused.append(refused)

        dependent = _make_analyze("task_2", depends_on_ids=["task_1"], goal_id=goal.id)
        id_to_node = {refused.id: refused, dependent.id: dependent}

        result = strategy_wf._filter_candidates([dependent], id_to_node)

        assert result == []
        assert dependent in strategy_wf.output.refused
        assert dependent._refusal is True
        assert len(strategy_wf.output.refused) == 2
        assert len(refused._details) == 1
        assert len(dependent._details) == 1

    def test_unrelated_candidate_is_kept(self, strategy_wf):
        goal = _make_goal()
        refused = _make_retrieval("task_1", goal_id=goal.id)
        refused.refuse("low confidence")
        refused.refuse("no matching goals")
        strategy_wf.output.refused.append(refused)

        unrelated = _make_retrieval("task_3", goal_id=goal.id, title="Other Book")
        id_to_node = {refused.id: refused, unrelated.id: unrelated}

        result = strategy_wf._filter_candidates([unrelated], id_to_node)

        assert result == [unrelated]
        assert unrelated not in strategy_wf.output.refused
        assert len(strategy_wf.output.refused) == 1
        assert len(refused._details) == 2

    def test_propagates_transitively_through_chain(self, strategy_wf):
        goal = _make_goal()
        refused = _make_retrieval("task_1", goal_id=goal.id)
        refused.refuse("low confidence")
        refused.refuse("no matching goals")
        strategy_wf.output.refused.append(refused)

        mid = _make_analyze("task_2", depends_on_ids=["task_1"], goal_id=goal.id)
        downstream = _make_analyze("task_3", depends_on_ids=["task_2"], goal_id=goal.id)
        id_to_node = {refused.id: refused, mid.id: mid, downstream.id: downstream}

        result = strategy_wf._filter_candidates([mid, downstream], id_to_node)

        assert result == []
        assert mid in strategy_wf.output.refused
        assert downstream in strategy_wf.output.refused
        assert len(strategy_wf.output.refused) == 3
        assert len(refused._details) == 2
        assert len(mid._details) == 1
        assert len(downstream._details) == 1


class TestRemoveDuplicates:
    def test_no_duplicates_returns_all(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        result = strategy_wf._remove_duplicates([r1, r2])
        assert result == [r1, r2]

    def test_same_content_different_wording_is_deduplicated(self, strategy_wf):
        # description/reasoning/confidence differ, but the fields that
        # actually matter (title, target_goal) are identical
        r1 = _make_retrieval("task_1", title="Pride and Prejudice")
        r1.description = "Looking for Pride and Prejudice by Austen"
        r2 = _make_retrieval("task_2", title="Pride and Prejudice", confidence=0.95)
        r2.description = "User wants the book Pride and Prejudice"

        result = strategy_wf._remove_duplicates([r1, r2])

        assert result == [r1]

    def test_different_content_is_kept(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        result = strategy_wf._remove_duplicates([r1, r2])
        assert len(result) == 2

    def test_dependents_are_reassigned_to_surviving_duplicate(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Same Book")
        r2 = _make_retrieval("task_2", title="Same Book")
        dependent = _make_analyze("task_3", depends_on_ids=["task_2"])

        result = strategy_wf._remove_duplicates([r1, r2, dependent])

        assert result == [r1, dependent]
        assert dependent.get_depends_on() == ["task_1"]

    def test_same_content_different_goal_is_deduplicated_and_goals_merged(self, strategy_wf):
        # same title, but each targets a different goal - still the same
        # underlying task, so the survivor should carry both goal ids
        r1 = _make_retrieval("task_1", title="Same Book", goal_id="goal_a1b2c3d4")
        r2 = _make_retrieval("task_2", title="Same Book", goal_id="goal_ffffffff")

        result = strategy_wf._remove_duplicates([r1, r2])

        assert result == [r1]
        assert r1.target_goal == ["goal_a1b2c3d4", "goal_ffffffff"]


class TestAddToAccepted:
    def test_excess_strategies_go_to_buffer(self, strategy_wf):
        goal = _make_goal()
        strategy_wf.output.accepted = [
            _make_retrieval(f"task_{i}", title=f"Book {i}") for i in range(MAX_STRATEGIES)
        ]
        extra = _make_retrieval("task_16", goal_id=goal.id)
        strategy_wf.process_classification_result([extra], [goal])
        assert len(strategy_wf.output.buffer) == 1
        assert strategy_wf.output.buffer[0] is extra


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

    def test_duplicate_llm_id_is_removed_from_mapping(self, strategy_wf, caplog):
        import logging
        r1 = _make_retrieval("task_1", title="First")
        r2 = _make_retrieval("task_1", title="Second")
        with caplog.at_level(logging.WARNING):
            mapping = strategy_wf.set_llm_id([r1, r2])
        # the duplicate id is purged from the mapping entirely so no dependent
        # strategy can silently resolve to the wrong retrieval
        assert "task_1" not in mapping
        assert r2.id == "task_1"
        assert "Duplicate id" in caplog.text

    def test_duplicate_id_causes_dependent_analyses_to_be_refused(self, strategy_wf, caplog):
        import logging
        goal = _make_goal()
        # LLM assigned "task_1" to both retrievals by mistake — should have been task_1 and task_2
        r1 = _make_retrieval("task_1", title="Harry Potter", goal_id=goal.id)
        r2 = _make_retrieval("task_1", title="Lord of the Rings", goal_id=goal.id)
        a1 = _make_analyze("task_3", depends_on_ids=["task_1"], goal_id=goal.id)
        a2 = _make_analyze("task_4", depends_on_ids=["task_1"], goal_id=goal.id)

        with caplog.at_level(logging.WARNING):
            mapping = strategy_wf.set_llm_id([r1, r2, a1, a2])

        assert "Duplicate id: task_1" in caplog.text
        # "task_1" is removed from the mapping because it was a duplicate —
        # pointing both analyses to r1 would be wrong
        assert "task_1" not in mapping
        assert len(mapping) == 2

        strategy_wf.map_dependencies_to_internal_ids([r1, r2, a1, a2], mapping)

        # a1 and a2 both depended on "task_1", which is no longer in the mapping —
        # they are refused rather than silently resolved to the wrong retrieval
        assert a1._refusal is True
        assert a2._refusal is True

    def test_duplicate_retrieval_refuses_dependent_and_its_downstream(self, strategy_wf, caplog):
        import logging
        goal = _make_goal()
        # tasks refusal should propagate downstream
        r1 = _make_retrieval("task_1", title="Book A", goal_id=goal.id)
        r2 = _make_retrieval("task_1", title="Book B", goal_id=goal.id)
        a2 = _make_analyze("task_4", depends_on_ids=["task_1"], goal_id=goal.id)
        a3 = _make_analyze("task_5", depends_on_ids=["task_4"], goal_id=goal.id)

        r3 = _make_retrieval("task_2", title="Book C", goal_id=goal.id)
        a1 = _make_analyze("task_3", depends_on_ids=["task_2"], goal_id=goal.id)
        a4 = _make_analyze("task_6", depends_on_ids=["task_3"], goal_id=goal.id)


        with caplog.at_level(logging.WARNING):
            mapping = strategy_wf.set_llm_id([r1, r2, r3, a1])

        assert "task_1" in mapping
        assert "task_2" in mapping
        assert "task_3" in mapping
        assert "task_4" not in mapping
        assert "task_5" not in mapping
        assert "task_6" in mapping

        strategy_wf.map_dependencies_to_internal_ids([r1, r2, r3, a1, a2, a3, a4], mapping)

        assert a2.refusal == True
        assert a3.refusal == True
        
        


class TestMapDependencies:
    def test_translates_llm_ids_to_internal(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        llm_to_internal = strategy_wf.set_llm_id([r, a])
        strategy_wf.map_dependencies_to_internal_ids([r, a], llm_to_internal)
        assert a.depends_on[0] == r.id

    def test_flags_refusal_on_missing_dep(self, strategy_wf):
        a = _make_analyze("task_2", depends_on_ids=["task_99"])
        strategy_wf.map_dependencies_to_internal_ids([a], {})
        assert a._refusal is True

    def test_none_depends_on_marks_strategy_refused(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        a.depends_on = None
        strategy_wf.map_dependencies_to_internal_ids([a], {})
        assert a._refusal is True


class TestBuildModel:
    def test_raises_on_empty_strategy_types(self):
        with pytest.raises(TypeError):
            StrategyRequest.build_model([])

    def test_returned_model_has_strategies_field(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        assert "strategies" in model.model_fields
 
    def test_returned_model_instantiates_with_matching_strategy(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        instance = model(strategies=[_make_retrieval("task_1")])
        assert len(instance.strategies) == 1


class TestCheckStrategies:
    def test_non_list_is_wrapped_in_list(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        instance = model(strategies=_make_retrieval("task_1"))
        assert len(instance.strategies) == 1

    def test_duplicate_ids_are_deduplicated(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r1 = _make_retrieval("task_1", title="First Book")
        r2 = _make_retrieval("task_1", title="Second Book")
        instance = model(strategies=[r1, r2])
  
        assert len(instance.strategies) == 1

    def test_first_occurrence_is_kept_on_dedup(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r1 = _make_retrieval("task_1", title="First Book")
        r2 = _make_retrieval("task_1", title="Second Book")
        instance = model(strategies=[r1, r2])
        assert instance.strategies[0].title == "First Book"

    def test_none_id_items_are_skipped(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r = _make_retrieval("task_1")
        instance = model(strategies=[{"no_id_key": "value"}, r])
        assert len(instance.strategies) == 1
        assert instance.strategies[0].id == r.id

    def test_strategies_truncated_to_max(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        items = [_make_retrieval(f"task_{i}", title=f"Book {i}") for i in range(MAX_STRATEGIES + 3)]
        instance = model(strategies=items)
        assert len(instance.strategies) == MAX_STRATEGIES


class TestGetAcceptedIdToNode:
    def test_returns_dict_keyed_by_node_id(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        result = strategy_wf.output.get_accepted_id_to_node()
        assert r.id in result
        assert result[r.id] is r

    def test_empty_accepted_returns_empty_dict(self, strategy_wf):
        assert strategy_wf.output.get_accepted_id_to_node() == {}

    def test_multiple_nodes_all_keyed(self, strategy_wf):
        r1 = _make_retrieval("task_1")
        r2 = _make_retrieval("task_2", title="Book B")
        strategy_wf.output.accepted = [r1, r2]
        result = strategy_wf.output.get_accepted_id_to_node()
        assert len(result) == 2
        assert result[r1.id] is r1
        assert result[r2.id] is r2


class TestToSummary:
    def test_returns_ids_of_accepted_strategies(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        assert strategy_wf.output.to_summary() == {"strategy_ids": [r.id]}

    def test_empty_accepted_returns_empty_list(self, strategy_wf):
        assert strategy_wf.output.to_summary() == {"strategy_ids": []}


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
        assert request_classes == {RecommendationStrategy, FindByTitleRetrieval}

    def test_no_injection_when_only_retrieval_present(self, strategy_wf):
        request_classes = {FindByTitleRetrieval}
        strategy_wf._inject_book_request_classes(request_classes)
        assert request_classes == {FindByTitleRetrieval}


class TestBuildStrategyRequest:
    def test_returns_model_for_retrieval_goal(self, strategy_wf):
        goal = _make_goal(node_type=BookNodeTypeEnum.FIND_TITLE)
        model = strategy_wf.build_strategy_request([goal])
        assert "strategies" in model.model_fields

    def test_analyze_goal_injects_retrieval_classes(self, strategy_wf):
        goal = _make_goal(node_type=BookNodeTypeEnum.RECOMMENDATION)
        model = strategy_wf.build_strategy_request([goal])
        assert "strategies" in model.model_fields

    def test_unsupported_node_type_raises(self, strategy_wf):
        goal = _make_goal(node_type=UnknownNodeTypeEnum.UNKNOWN)
        # TODO: add a longer lists of goals and get size
        with pytest.raises(TypeError):
            strategy_wf.build_strategy_request([goal])


class TestFormatSystemGoals:
    def test_returns_assistant_message_with_id_and_description(self, strategy_wf):
        goal = _make_goal()
        msg = strategy_wf._format_system_goals([goal])
        data = json.loads(msg.content)
        assert len(data) == 1
        assert data[0]["id"] == goal.id
        assert data[0]["description"] == goal.description

    def test_multiple_goals_all_included(self, strategy_wf):
        g1 = _make_goal(node_type=BookNodeTypeEnum.FIND_TITLE)
        g2 = _make_goal(node_type=BookNodeTypeEnum.RECOMMENDATION)
        msg = strategy_wf._format_system_goals([g1, g2])
        data = json.loads(msg.content)
        assert len(data) == 2
        assert {d["id"] for d in data} == {g1.id, g2.id}


class TestGetStrategiesIds:
    def test_returns_set_of_strategy_ids(self, strategy_wf):
        r1 = _make_retrieval("task_1")
        r2 = _make_retrieval("task_2", title="Book B")
        assert strategy_wf.get_strategies_ids([r1, r2]) == {r1.id, r2.id}

    def test_empty_list_returns_empty_set(self, strategy_wf):
        assert strategy_wf.get_strategies_ids([]) == set()


class TestFinalizeResult:
    def test_ok_when_order_and_accepted(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf.output.execution_order = [r.id]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is True

    def test_not_ok_when_no_execution_order(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is False

    def test_not_ok_when_no_accepted(self, strategy_wf):
        strategy_wf.output.execution_order = ["task_1"]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is False


class TestRemoveCycles:
    def test_skips_node_id_not_in_accepted(self, strategy_wf, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            strategy_wf._remove_cycles({"phantom_id": 1})
        assert "phantom_id" in caplog.text
        assert strategy_wf.output.refused == []

    def test_cycle_node_moves_to_refused(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf._remove_cycles({r.id: 1})
        assert r in strategy_wf.output.refused
        assert r not in strategy_wf.output.accepted

    def test_cycle_node_marked_as_refused(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf._remove_cycles({r.id: 1})
        assert r._refusal is True

    def test_cycle_reason_recorded_on_node(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf._remove_cycles({r.id: 1})
        assert "Cycle detected in dependency graph" in r._refusal_reasons
        assert r in strategy_wf.output.refused

    def test_degree_zero_node_is_not_moved(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf._remove_cycles({r.id: 0})
        assert r in strategy_wf.output.accepted
        assert strategy_wf.output.refused == []


class TestRun:
    async def test_raises_on_empty_goals(self, strategy_wf):
        strategy_wf.sse_stream.send_ui_loading = AsyncMock()
        with pytest.raises(ValueError):
            await strategy_wf.run(UserMessage(content="test"), [])

    async def test_happy_path_accepts_strategy(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval("task_1", goal_id=goal.id)
        parse_result = StrategyRequest.build_model([FindByTitleRetrieval])(strategies=[r])

        tool_call = MagicMock()
        tool_call.function.parsed_arguments = parse_result
        assistant_msg = MagicMock()
        assistant_msg.tool_calls = [tool_call]

        strategy_wf.sse_stream.send_ui_loading = AsyncMock()
        strategy_wf.run_llm_call = AsyncMock(return_value=assistant_msg)

        await strategy_wf.run(UserMessage(content="Find me a book"), [goal])
        assert strategy_wf.result.ok is True
        assert len(strategy_wf.output.accepted) == 1
