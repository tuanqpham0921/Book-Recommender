"""What `AppWorkflow` guarantees to every unit of work in the app.

Two things are pinned here rather than in any one slice's tests, because they
are what the uniform `run(node_input)` shape rests on:

1. **Every registered executor can actually be constructed from the context its
   spec declares, and comes up with its declared output envelope.** This went
   untested long enough for `_generic_output_type` to go missing entirely —
   nothing constructed a book executor outside a live request, so nothing
   noticed. It is parameterized off the live registry, so a new slice is
   covered the day it is registered.
2. **Narrowing the context is what resolves a node's services**, and it does so
   without copying the ones that must keep their identity.

The selection rule that used to live here (`find_artifact` / `require_artifact`,
picking artifacts by type) moved to `build_input` — see test_node_input.py.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.node_input import NodeInput, WorkflowInput
from app.registry import REGISTRY
from db.stores.base_store import BaseStore
from db.stores.book_store import BookStore

# Every node that can actually run, with the spec that says how to build it.
RUNNABLE_SPECS = [spec for spec in REGISTRY.specs if spec.executor is not None]


def spec_id(spec) -> str:
    return spec.executor.__name__


@pytest.mark.parametrize("spec", RUNNABLE_SPECS, ids=spec_id)
def test_registered_executor_constructs_with_its_output_envelope(
    spec, request_context
):
    wf = spec.executor(spec.context.narrow(request_context))

    declared = spec.executor._generic_output_type()
    assert declared is not None, f"{spec.executor.__name__} pinned no output type"
    assert isinstance(wf.result, declared)


@pytest.mark.parametrize("spec", RUNNABLE_SPECS, ids=spec_id)
def test_registered_executor_reads_services_off_the_context(spec, request_context):
    wf = spec.executor(spec.context.narrow(request_context))

    # identity, not equality: narrowing rebuilds the model, and a *copied*
    # SSEStream would enqueue into a queue nothing reads without raising
    assert wf.sse_stream is request_context.sse_stream
    assert wf.llm_client is request_context.llm_client
    assert wf.user_message is request_context.user_message
    assert wf.app_env == request_context.app_env


@pytest.mark.parametrize("spec", RUNNABLE_SPECS, ids=spec_id)
def test_registered_executor_resolves_its_own_store(spec, request_context):
    """A node's `store` shorthand must resolve to the store class its own
    property is annotated with — not to whatever store happens to be on the
    request. The by-class lookup now happens in `narrow`, which is what makes
    this checkable at dispatch instead of at the first query."""
    wf = spec.executor(spec.context.narrow(request_context))
    declared = type(wf).store.fget.__annotations__["return"]

    assert isinstance(wf.store, declared)
    assert wf.store is request_context.stores[declared]


class TestNarrowing:
    def test_narrow_rejects_a_store_the_request_does_not_have(
        self, make_request_context
    ):
        """The whole point of narrowing at dispatch: a request with no
        BookStore fails here, naming the store, rather than deep inside a
        node's first query."""
        from app.domains.books.external import BookRequestContext

        ctx = make_request_context(stores={})
        with pytest.raises(LookupError, match="BookStore"):
            BookRequestContext.narrow(ctx)

    def test_narrow_rejects_a_mis_keyed_store(self, make_request_context):
        # the value is checked, not just the key — so a mapping wired to the
        # wrong store fails here rather than at the first query, and says so in
        # terms of what it actually found
        class _OtherStore(BaseStore):
            pass

        ctx = make_request_context(stores={_OtherStore: MagicMock(spec=BookStore)})
        with pytest.raises(LookupError, match="holds a BookStore, not a _OtherStore"):
            ctx.require_store(_OtherStore)

    def test_base_narrow_is_identity(self, request_context):
        """A node that declares no services view is handed the context as-is —
        no rebuild, so the default costs nothing at dispatch."""
        from app.common.request_context import RequestContext

        assert RequestContext.narrow(request_context) is request_context


class _Output(NodeWorkflowOutput):
    def to_summary(self) -> dict[str, Any]:
        return {}


class _Workflow(AppWorkflow[_Output]):
    async def run(self, node_input: NodeInput) -> None:
        self.record.ok = True


class TestOutputTypeGuard:
    def test_unparameterized_subclass_fails_at_construction(self, request_context):
        class _Unpinned(AppWorkflow):
            async def run(self, node_input: WorkflowInput) -> None: ...

        # named at construction rather than surfacing much later as
        # "output was not initialized" from somewhere inside run()
        with pytest.raises(TypeError, match="pinned no output type"):
            _Unpinned(request_context)
