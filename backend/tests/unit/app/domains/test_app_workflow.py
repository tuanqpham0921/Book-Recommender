"""What `AppWorkflow` guarantees to every unit of work in the app.

Two things are pinned here rather than in any one slice's tests, because they
are what the uniform `run(query, artifacts)` shape rests on:

1. **Every registered executor can actually be constructed from a
   RequestContext, and comes up with its declared output envelope.** This went
   untested long enough for `_generic_output_type` to go missing entirely —
   nothing constructed a book executor outside a live request, so nothing
   noticed. It is parameterized off the live registry, so a new slice is
   covered the day it is registered.
2. **Artifacts are selected by type, not by key** — the rule that lets one node
   be fed by one upstream node or five without the caller and the callee
   agreeing on a string.
"""

from typing import Any

import pytest

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.registry import EXECUTORS_CLS_MAPPING
from airglider import StepFailure


@pytest.mark.parametrize(
    "executor_cls",
    EXECUTORS_CLS_MAPPING.values(),
    ids=lambda cls: cls.__name__,
)
def test_registered_executor_constructs_with_its_output_envelope(
    executor_cls, request_context
):
    wf = executor_cls(request_context)

    declared = executor_cls._generic_output_type()
    assert declared is not None, f"{executor_cls.__name__} pinned no output type"
    assert isinstance(wf.result, declared)


@pytest.mark.parametrize(
    "executor_cls",
    EXECUTORS_CLS_MAPPING.values(),
    ids=lambda cls: cls.__name__,
)
def test_registered_executor_reads_services_off_the_context(
    executor_cls, request_context
):
    wf = executor_cls(request_context)

    assert wf.sse_stream is request_context.sse_stream
    assert wf.llm_client is request_context.llm_client
    assert wf.app_env == request_context.app_env
    # book nodes reach the request-scoped store the same way
    assert wf.store is request_context.book_store


class _Output(NodeWorkflowOutput):
    def to_summary(self) -> dict[str, Any]:
        return {}


class _OtherOutput(NodeWorkflowOutput):
    def to_summary(self) -> dict[str, Any]:
        return {}


class _Workflow(AppWorkflow[_Output]):
    async def run(self, query: str, artifacts: dict[str, Any]) -> None:
        self.record.ok = True


class TestArtifacts:
    def test_find_artifact_ignores_the_key(self, request_context):
        wanted = _Output()
        wf = _Workflow(request_context)
        # keys are provenance (upstream goal ids), never a contract
        assert wf.find_artifact({"7": wanted}, _Output) is wanted

    def test_find_artifact_returns_none_when_absent(self, request_context):
        wf = _Workflow(request_context)
        assert wf.find_artifact({"1": _OtherOutput()}, _Output) is None

    def test_require_artifact_aborts_as_a_controlled_failure(self, request_context):
        # StepFailure, not a crash: Workflow.__call__ records it and the turn
        # ends cleanly rather than raising into the request
        wf = _Workflow(request_context)
        with pytest.raises(StepFailure, match="_Output"):
            wf.require_artifact({"1": _OtherOutput()}, _Output)

    def test_require_artifact_names_what_it_got(self, request_context):
        wf = _Workflow(request_context)
        with pytest.raises(StepFailure, match="_OtherOutput"):
            wf.require_artifact({"1": _OtherOutput()}, _Output)

    def test_artifact_property_keys_on_the_stamped_id(self, request_context):
        wf = _Workflow(request_context)
        wf.result.id = "3"
        assert wf.artifact == {"3": wf.result}

    def test_artifact_property_falls_back_to_the_class_name(self, request_context):
        # the planner runs before any goal id exists
        wf = _Workflow(request_context)
        assert wf.artifact == {"_Workflow": wf.result}


class TestOutputTypeGuard:
    def test_unparameterized_subclass_fails_at_construction(self, request_context):
        class _Unpinned(AppWorkflow):
            async def run(self, query: str, artifacts: dict[str, Any]) -> None: ...

        # named at construction rather than surfacing much later as
        # "output was not initialized" from somewhere inside run()
        with pytest.raises(TypeError, match="pinned no output type"):
            _Unpinned(request_context)
