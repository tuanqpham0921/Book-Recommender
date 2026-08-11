"""`build_input` — how a node's declared input gets filled from what ran before.

This is where the select-by-type rule now lives, so the guarantees that used to
be spread across every node body are asserted once here:

- fields match on **type**, never on the artifact's key (keys are provenance);
- an optional or list field that finds nothing is *empty*, not an error — that
  is what lets a node with a real fallback declare the dependency it prefers
  without making it mandatory;
- a required field that finds nothing raises, and the error **names the field**
  — which is the "what is missing" answer an agentic node would hand back to
  the planner.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.node_input import NodeInput, WorkflowInput, build_input


class _Books(NodeWorkflowOutput):
    label: str = ""

    def to_summary(self) -> dict[str, Any]:
        return {}


class _Report(NodeWorkflowOutput):
    def to_summary(self) -> dict[str, Any]:
        return {}


class _TakesNothing(NodeInput):
    pass


class _TakesMany(NodeInput):
    anchors: list[_Books] = []


class _TakesOptional(NodeInput):
    anchor: _Books | None = None


class _TakesRequired(NodeInput):
    anchor: _Books


class _NoQuery(WorkflowInput):
    anchor: _Books


class TestQuery:
    def test_query_is_filled_from_the_goal_text(self):
        assert build_input(_TakesNothing, "find dune", {}).query == "find dune"

    def test_a_workflow_input_without_query_does_not_get_one(self):
        """`WorkflowInput` carries nothing — TaskRunnerInput takes only a plan,
        and a `query` it would never read has no business being set."""
        built = build_input(_NoQuery, "ignored", {"1": _Books()})
        assert not hasattr(built, "query")


class TestSelectionByType:
    def test_matches_on_type_not_on_key(self):
        wanted = _Books()
        built = build_input(_TakesOptional, "q", {"some-goal-id": wanted})
        assert built.anchor is wanted

    def test_a_list_field_collects_every_match(self):
        first, second = _Books(label="a"), _Books(label="b")
        built = build_input(
            _TakesMany, "q", {"1": first, "2": _Report(), "3": second}
        )
        assert built.anchors == [first, second]

    def test_a_node_that_declares_nothing_ignores_what_it_is_handed(self):
        """Structurally cannot consume upstream output — the artifact is
        dropped rather than quietly shaping the node's work."""
        built = build_input(_TakesNothing, "q", {"1": _Books()})
        assert built.model_dump() == {"query": "q"}


class TestEmptyIsNotAnError:
    def test_a_list_field_with_no_match_is_empty(self):
        built = build_input(_TakesMany, "q", {"1": _Report()})
        assert built.anchors == []

    def test_an_optional_field_with_no_match_is_none(self):
        built = build_input(_TakesOptional, "q", {"1": _Report()})
        assert built.anchor is None


class TestRequiredFields:
    def test_a_required_field_with_no_match_raises(self):
        with pytest.raises(ValidationError):
            build_input(_TakesRequired, "q", {"1": _Report()})

    def test_the_error_names_the_missing_field(self):
        """The name is the payload: it is what a node would send back to the
        planner to ask for a goal that produces the shape it is short of."""
        with pytest.raises(ValidationError) as excinfo:
            build_input(_TakesRequired, "q", {})

        assert [err["loc"] for err in excinfo.value.errors()] == [("anchor",)]
