"""Tests for StrategyClassificationWorkflow pure logic methods."""

import json
from collections import defaultdict

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.common.messages import ToolMessage, UserMessage
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


def _make_retrieval(
    id_str="task_1", goal_id="goal_a1b2c3d4", title="Test Book", confidence=0.9
):
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


class TestGetGraphIndegree:
    def test_retrieval_only_has_zero_indegree_and_empty_graph(self, strategy_wf):
        r = _make_retrieval("task_1")
        graph, indegree = strategy_wf._get_graph_indegree([r])
        assert indegree[r.id] == 0
        assert graph[r.id] == []

    def test_single_dependency_increments_indegree_and_adds_edge(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        graph, indegree = strategy_wf._get_graph_indegree([r, a])
        assert indegree[a.id] == 1
        assert indegree[r.id] == 0
        assert graph[r.id] == [a.id]
        assert len(graph) == 1
        assert len(indegree) == 2

    def test_multiple_dependencies_sum_indegree(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        a = _make_analyze("task_3", depends_on_ids=["task_1", "task_2"])
        graph, indegree = strategy_wf._get_graph_indegree([r1, r2, a])
        assert indegree[a.id] == 2
        assert indegree[r1.id] == 0
        assert indegree[r2.id] == 0
        assert graph[r1.id] == [a.id]
        assert graph[r2.id] == [a.id]
        assert len(graph) == 2
        assert len(indegree) == 3

    def test_fan_out_appends_all_dependents_to_same_edge(self, strategy_wf):
        r = _make_retrieval("task_1")
        a1 = _make_analyze("task_2", depends_on_ids=["task_1"])
        a2 = _make_analyze("task_3", depends_on_ids=["task_1"])
        graph, indegree = strategy_wf._get_graph_indegree([r, a1, a2])
        assert graph[r.id] == [a1.id, a2.id]
        assert indegree[a1.id] == 1
        assert indegree[a2.id] == 1

    def test_dependency_outside_candidates_has_no_indegree_entry(self, strategy_wf):
        # only the analyze node is passed in; its dependency was filtered out
        # upstream and never gets its own indegree entry
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        graph, indegree = strategy_wf._get_graph_indegree([a])
        assert "task_1" not in indegree
        assert graph["task_1"] == [a.id]

    def test_empty_candidates_returns_empty_graph_and_indegree(self, strategy_wf):
        graph, indegree = strategy_wf._get_graph_indegree([])
        assert dict(graph) == {}
        assert dict(indegree) == {}


class TestSortGraph:
    """Pure Kahn's-algorithm topological sort - given a raw graph/indegree,
    independent of how _get_graph_indegree built them."""

    def test_no_dependencies_all_nodes_in_order(self, strategy_wf):
        indegree = defaultdict(int, {"task_1": 0, "task_2": 0})
        order = strategy_wf._sort_graph(defaultdict(list), indegree)
        assert set(order) == {"task_1", "task_2"}
        assert len(order) == 2

    def test_simple_chain_respects_dependency_order(self, strategy_wf):
        indegree = defaultdict(int, {"task_1": 0, "task_2": 1})
        graph = defaultdict(list, {"task_1": ["task_2"]})
        order = strategy_wf._sort_graph(graph, indegree)
        assert order == ["task_1", "task_2"]

    def test_fan_in_both_predecessors_precede_dependent(self, strategy_wf):
        indegree = defaultdict(int, {"task_1": 0, "task_2": 0, "task_3": 2})
        graph = defaultdict(list, {"task_1": ["task_3"], "task_2": ["task_3"]})
        order = strategy_wf._sort_graph(graph, indegree)
        assert order.index("task_1") < order.index("task_3")
        assert order.index("task_2") < order.index("task_3")

    def test_cycle_produces_incomplete_order(self, strategy_wf):
        indegree = defaultdict(int, {"task_1": 1, "task_2": 1})
        graph = defaultdict(list, {"task_1": ["task_2"], "task_2": ["task_1"]})
        order = strategy_wf._sort_graph(graph, indegree)
        assert order == []
        assert len(order) != len(indegree)

    def test_empty_graph_returns_empty_order(self, strategy_wf):
        order = strategy_wf._sort_graph(defaultdict(list), defaultdict(int))
        assert order == []


class TestCreateExecutionOrder:
    """_create_execution_order = _sort_graph + cycle cleanup, exercised here
    with hand-built graph/indegree rather than through _get_graph_indegree."""

    def test_no_cycle_returns_full_order_unchanged(self, strategy_wf):
        r = _make_retrieval("task_1")
        id_to_node = {r.id: r}
        order = strategy_wf._create_execution_order(
            defaultdict(list), defaultdict(int, {r.id: 0}), id_to_node
        )
        assert order == [r.id]
        assert strategy_wf.output.refused == []

    def test_cycle_nodes_removed_from_order_and_refused(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        id_to_node = {a.id: a, b.id: b}
        graph = defaultdict(list, {"task_1": ["task_2"], "task_2": ["task_1"]})
        indegree = defaultdict(int, {"task_1": 1, "task_2": 1})

        order = strategy_wf._create_execution_order(graph, indegree, id_to_node)

        assert order == []
        assert a in strategy_wf.output.refused
        assert b in strategy_wf.output.refused
        # cycle_nodes is a set, so which of a/b gets the custom message vs.
        # the recursive default varies - just confirm the custom message
        # from _create_execution_order was actually used on one of them
        assert "Rejected: Node in a cycle path" in a._details + b._details

    def test_non_cycle_node_survives_alongside_a_cycle(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        r = _make_retrieval("task_3")
        id_to_node = {a.id: a, b.id: b, r.id: r}
        graph = defaultdict(list, {"task_1": ["task_2"], "task_2": ["task_1"]})
        indegree = defaultdict(int, {"task_1": 1, "task_2": 1, "task_3": 0})

        order = strategy_wf._create_execution_order(graph, indegree, id_to_node)

        assert order == [r.id]
        assert r not in strategy_wf.output.refused


class TestExecutionOrder:
    def test_single_retrieval(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf._build_execution_order([r])
        assert strategy_wf.output.execution_order == [r.id]

    def test_simple_chain(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf._build_execution_order([r, a])
        assert strategy_wf.output.execution_order == [r.id, a.id]

    def test_parallel_retrievals(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        strategy_wf._build_execution_order([r1, r2])
        assert set(strategy_wf.output.execution_order) == {r1.id, r2.id}

    def test_fan_in_respects_dependency_order(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="Book A")
        r2 = _make_retrieval("task_2", title="Book B")
        a = _make_analyze("task_3", depends_on_ids=["task_1", "task_2"])
        strategy_wf._build_execution_order([r1, r2, a])
        order = strategy_wf.output.execution_order
        assert order.index(r1.id) < order.index(a.id)
        assert order.index(r2.id) < order.index(a.id)


class TestCycleDetection:
    def test_cycle_produces_empty_execution_order(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf._build_execution_order([a, b])
        assert strategy_wf.output.execution_order == []

    def test_cycle_moves_nodes_to_refused(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        strategy_wf._build_execution_order([a, b])
        assert len(strategy_wf.output.refused) == 2
        assert len(strategy_wf.output.accepted) == 0
        assert a._refusal is True
        assert b._refusal is True

    def test_non_cycle_nodes_are_not_refused(self, strategy_wf):
        # task_1/task_2 form a cycle, task_3 has no dependencies and should
        # pass through untouched
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        r = _make_retrieval("task_3")
        strategy_wf._build_execution_order([a, b, r])
        assert strategy_wf.output.execution_order == [r.id]
        assert r._refusal is False
        assert r not in strategy_wf.output.refused


class TestGetCandidates:
    def test_good_strategy_passes(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id)
        result = strategy_wf._get_candidates([r], [goal])
        assert result == [r]
        assert len(strategy_wf.output.refused) == 0

    def test_low_confidence_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id, confidence=0.3)
        result = strategy_wf._get_candidates([r], [goal])
        assert result == []
        assert len(strategy_wf.output.refused) == 1

    def test_missing_target_goal_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id="goal_ffffffff")
        result = strategy_wf._get_candidates([r], [goal])
        assert len(strategy_wf.output.refused) == 1
        assert result == []

    def test_empty_target_goal_goes_to_refused(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval(id_str="task_1", goal_id=goal.id)
        r.target_goal = []
        result = strategy_wf._get_candidates([r], [goal])
        assert len(strategy_wf.output.refused) == 1
        assert len(result) == 0


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

    def test_same_content_different_goal_is_deduplicated_and_goals_merged(
        self, strategy_wf
    ):
        # same title, but each targets a different goal - still the same
        # underlying task, so the survivor should carry both goal ids
        r1 = _make_retrieval("task_1", title="Same Book", goal_id="goal_a1b2c3d4")
        r2 = _make_retrieval("task_2", title="Same Book", goal_id="goal_ffffffff")

        result = strategy_wf._remove_duplicates([r1, r2])

        assert result == [r1]
        assert r1.target_goal == ["goal_a1b2c3d4", "goal_ffffffff"]


class TestAddToAccepted:
    def test_excess_strategies_go_to_buffer(self, strategy_wf):
        nodes = [
            _make_retrieval(f"task_{i}", title=f"Book {i}")
            for i in range(MAX_STRATEGIES)
        ]
        extra = _make_retrieval("task_extra")
        id_to_node = {n.id: n for n in nodes + [extra]}
        order = [n.id for n in nodes] + [extra.id]

        strategy_wf._add_to_accepted(order, id_to_node)

        assert len(strategy_wf.output.accepted) == MAX_STRATEGIES
        assert len(strategy_wf.output.buffer) == 1
        assert strategy_wf.output.buffer[0] is extra

    def test_within_limit_all_go_to_accepted(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf._add_to_accepted([r.id], {r.id: r})
        assert strategy_wf.output.accepted == [r]
        assert strategy_wf.output.buffer == []


class TestSetLlmId:
    def test_replaces_id_with_internal_format(self, strategy_wf):
        r = _make_retrieval("task_1")
        original_llm_id = r.id
        mapping = strategy_wf._set_llm_id([r])
        assert r.id != original_llm_id
        assert mapping[original_llm_id] == r.id
        assert r._llm_id == original_llm_id

    def test_returns_complete_mapping(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="A")
        r2 = _make_retrieval("task_2", title="B")
        assert len(strategy_wf._set_llm_id([r1, r2])) == 2

    def test_duplicate_llm_id_keeps_first_occurrence_in_mapping(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="First")
        r2 = _make_retrieval("task_1", title="Second")
        mapping = strategy_wf._set_llm_id([r1, r2])
        # the first occurrence keeps its original llm_id mapping untouched
        assert mapping["task_1"] == r1.id
        assert r1._llm_id == "task_1"

    def test_duplicate_llm_id_gets_new_random_id(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="First")
        r2 = _make_retrieval("task_1", title="Second")
        mapping = strategy_wf._set_llm_id([r1, r2])
        # the duplicate is assigned a fresh random llm_id so nothing can
        # legitimately depend on it
        assert r2._llm_id != "task_1"
        assert r2._llm_id in mapping
        assert mapping[r2._llm_id] == r2.id
        assert len(mapping) == 2

    def test_duplicate_llm_id_adds_detail_note(self, strategy_wf):
        r1 = _make_retrieval("task_1", title="First")
        r2 = _make_retrieval("task_1", title="Second")
        strategy_wf._set_llm_id([r1, r2])
        assert "duplicate llm_id, created a new one" in r2._details

    def test_dependents_resolve_to_first_occurrence_on_duplicate(self, strategy_wf):
        goal = _make_goal()
        r1 = _make_retrieval("task_1", title="Harry Potter", goal_id=goal.id)
        r2 = _make_retrieval("task_1", title="Lord of the Rings", goal_id=goal.id)
        a1 = _make_analyze("task_3", depends_on_ids=["task_1"], goal_id=goal.id)

        mapping = strategy_wf._set_llm_id([r1, r2, a1])
        strategy_wf._map_dependencies_to_internal_ids([r1, r2, a1], mapping)

        assert a1.depends_on == [r1.id]
        assert a1._refusal is False


class TestMapDependencies:
    def test_translates_llm_ids_to_internal(self, strategy_wf):
        r = _make_retrieval("task_1")
        a = _make_analyze("task_2", depends_on_ids=["task_1"])
        llm_to_internal = strategy_wf._set_llm_id([r, a])
        strategy_wf._map_dependencies_to_internal_ids([r, a], llm_to_internal)
        assert a.depends_on[0] == r.id

    def test_flags_refusal_on_missing_dep(self, strategy_wf):
        a = _make_analyze("task_2", depends_on_ids=["task_99"])
        strategy_wf._map_dependencies_to_internal_ids([a], {})
        assert a._refusal is True

    def test_none_depends_on_marks_strategy_refused(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        a.depends_on = None
        strategy_wf._map_dependencies_to_internal_ids([a], {})
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
        instance = model(strategies=[_make_retrieval("task_1").model_dump()])
        assert len(instance.strategies) == 1


class TestCaptureAndFilter:
    """capture_and_filter only accepts raw dicts (as the LLM response
    delivers them) — it looks up the concrete class via NODE_TYPE_TO_CLS
    using each dict's `node_type` key, so items must be dicts, not
    already-constructed BaseRequest instances."""

    def test_non_list_is_wrapped_in_list(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        instance = model(strategies=_make_retrieval("task_1").model_dump())
        assert len(instance.strategies) == 1

    def test_duplicate_ids_are_not_deduplicated_at_model_level(self):
        # dedup now happens later, during _set_llm_id — the model itself
        # keeps every syntactically valid strategy
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r1 = _make_retrieval("task_1", title="First Book").model_dump()
        r2 = _make_retrieval("task_1", title="Second Book").model_dump()
        instance = model(strategies=[r1, r2])
        assert len(instance.strategies) == 2

    def test_invalid_items_are_filtered_into_invalid_strategies(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r = _make_retrieval("task_1").model_dump()
        instance = model(strategies=[{"no_id_key": "value"}, r])
        assert len(instance.strategies) == 1
        assert instance.strategies[0].id == r["id"]
        assert instance._invalid_strategies == [{"no_id_key": "value"}]

    def test_strategies_truncated_to_max_overflow_captured(self):
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        items = [
            _make_retrieval(f"task_{i}", title=f"Book {i}").model_dump()
            for i in range(MAX_STRATEGIES + 3)
        ]
        instance = model(strategies=items)
        assert len(instance.strategies) == MAX_STRATEGIES
        assert len(instance._overflow_strategies) == 3

    def test_already_constructed_instance_is_rejected(self):
        # only raw dicts are accepted; a pre-built BaseRequest instance
        # falls into the `else` branch and is treated as invalid
        model = StrategyRequest.build_model([FindByTitleRetrieval])
        r = _make_retrieval("task_1")
        instance = model(strategies=[r])
        assert instance.strategies == []
        assert instance._invalid_strategies == [r]


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
        model = strategy_wf._build_strategy_request([goal])
        assert "strategies" in model.model_fields

    def test_analyze_goal_injects_retrieval_classes(self, strategy_wf):
        goal = _make_goal(node_type=BookNodeTypeEnum.RECOMMENDATION)
        model = strategy_wf._build_strategy_request([goal])
        assert "strategies" in model.model_fields

    def test_unsupported_node_type_raises(self, strategy_wf):
        goal = _make_goal(node_type=UnknownNodeTypeEnum.UNKNOWN)
        # TODO: add a longer lists of goals and get size
        with pytest.raises(TypeError):
            strategy_wf._build_strategy_request([goal])


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


class TestRecordToolCall:
    def test_appends_tool_message(self, strategy_wf):
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "StrategyRequest"

        strategy_wf._record_tool_call(tool_call)

        assert len(strategy_wf.messages) == 1
        msg = strategy_wf.messages[0]
        assert isinstance(msg, ToolMessage)
        assert msg.name == "StrategyRequest"
        assert msg.tool_call_id == "call_1"
        assert msg.content is strategy_wf.output

    def test_multiple_calls_append_multiple_messages(self, strategy_wf):
        tool_call_1 = MagicMock(id="call_1")
        tool_call_1.function.name = "StrategyRequest"
        tool_call_2 = MagicMock(id="call_2")
        tool_call_2.function.name = "StrategyRequest"

        strategy_wf._record_tool_call(tool_call_1)
        strategy_wf._record_tool_call(tool_call_2)

        assert len(strategy_wf.messages) == 2
        assert [m.tool_call_id for m in strategy_wf.messages] == ["call_1", "call_2"]


class TestFinalizeResult:
    def test_ok_when_order_and_accepted(self, strategy_wf):
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf.output.execution_order = [r.id]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is True

    def test_ok_when_accepted_even_without_execution_order(self, strategy_wf):
        # finalize_result only looks at accepted now
        r = _make_retrieval("task_1")
        strategy_wf.output.accepted = [r]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is True

    def test_not_ok_when_no_accepted(self, strategy_wf):
        strategy_wf.output.execution_order = ["task_1"]
        strategy_wf.finalize_result()
        assert strategy_wf.result.ok is False


class TestRemoveCycles:
    def test_cycle_node_moves_to_refused(self, strategy_wf):
        r = _make_retrieval("task_1")
        graph = defaultdict(list)
        id_to_node = {r.id: r}
        remove_ids = set()
        strategy_wf._reject_dependent_on(graph, r.id, remove_ids, id_to_node)
        assert r in strategy_wf.output.refused
        assert r._refusal is True
        assert remove_ids == {r.id}

    def test_already_removed_node_is_skipped(self, strategy_wf):
        r = _make_retrieval("task_1")
        graph = defaultdict(list)
        id_to_node = {r.id: r}
        remove_ids = {r.id}
        strategy_wf._reject_dependent_on(graph, r.id, remove_ids, id_to_node)
        assert strategy_wf.output.refused == []

    def test_propagates_to_downstream_dependents(self, strategy_wf):
        a = _make_analyze("task_1", depends_on_ids=["task_2"])
        b = _make_analyze("task_2", depends_on_ids=["task_1"])
        graph = defaultdict(list, {a.id: [b.id]})
        id_to_node = {a.id: a, b.id: b}
        remove_ids = set()
        strategy_wf._reject_dependent_on(graph, a.id, remove_ids, id_to_node)
        assert a in strategy_wf.output.refused
        assert b in strategy_wf.output.refused
        assert remove_ids == {a.id, b.id}

    def test_cycle_reason_recorded_on_node(self, strategy_wf):
        r = _make_retrieval("task_1")
        graph = defaultdict(list)
        id_to_node = {r.id: r}
        strategy_wf._reject_dependent_on(graph, r.id, set(), id_to_node)
        assert "Rejected: Node depends on a rejected node" in r._details

    def test_custom_message_is_recorded(self, strategy_wf):
        r = _make_retrieval("task_1")
        graph = defaultdict(list)
        id_to_node = {r.id: r}
        strategy_wf._reject_dependent_on(
            graph, r.id, set(), id_to_node, message="custom test reason"
        )
        assert "Rejected: custom test reason" in r._details


class TestRun:
    async def test_raises_on_empty_goals(self, strategy_wf):
        strategy_wf.sse_stream.send_ui_loading = AsyncMock()
        with pytest.raises(ValueError):
            await strategy_wf.run(UserMessage(content="test"), [])

    async def test_happy_path_accepts_strategy(self, strategy_wf):
        goal = _make_goal()
        r = _make_retrieval("task_1", goal_id=goal.id)
        # capture_and_filter only accepts raw dicts, not already-built instances
        parse_result = StrategyRequest.build_model([FindByTitleRetrieval])(
            strategies=[r.model_dump()]
        )

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "StrategyRequest"
        tool_call.function.parsed_arguments = parse_result
        assistant_msg = MagicMock()
        assistant_msg.tool_calls = [tool_call]

        strategy_wf.sse_stream.send_ui_loading = AsyncMock()
        strategy_wf.run_llm_call = AsyncMock(return_value=assistant_msg)

        await strategy_wf.run(UserMessage(content="Find me a book"), [goal])
        assert strategy_wf.result.ok is True
        assert len(strategy_wf.output.accepted) == 1
