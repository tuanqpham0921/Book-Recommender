"""One descriptor per node — the single source `app/registry.py` derives from.

A node is a vertical slice exporting one `SPEC`; the registry derives every
lookup from the collected specs, so adding a capability means adding a folder
and listing its `SPEC`, not editing parallel dicts that can drift apart.

`node_type` is the name the planner LLM emits, and must match the `Literal`
default on the request schema — pydantic's discriminator for picking the class
back out of a tool call. `__post_init__` enforces that; a mismatch would
otherwise only show up as a failed eval.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.common.request_context import RequestContext
from app.domains.node_input import NodeInput, WorkflowInput

if TYPE_CHECKING:
    from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
    from app.domains.base_request import BaseRequest


class NodeTier(str, Enum):
    """Catalog grouping. The value is the section heading the planner LLM
    reads in `Registry.format_catalog()`, so it is prompt text."""

    RETRIEVAL = "Retrieval — lookup or fetch data"
    ANALYZE = "Analyze — interpret, compare, or recommend using retrieved data"


@dataclass(frozen=True)
class NodeSpec:
    """Everything the system needs to know about one node.

    Three schemas, distinguished by who fills them in: `request` by the planner
    LLM, `input` by the task runner, `output` by the executor. (`request` and
    `input` converge eventually — the parsed args are an input the node
    currently produces for itself.)

    Args:
        node_type: The capability name the planner emits, e.g. "Retrieve_by_Title".
        tier: Which catalog section this node is listed under.
        request: The pydantic request schema. Its docstring IS the tool
            description the planner LLM reads.
        input: What this node is invoked with — declares which upstream shapes
            it can consume. The default accepts the goal text and nothing else,
            which is the right contract for a node with no dependencies.
        output: The result payload the executor fills in.
        executor: The workflow that runs it. None for a node that is registered
            for planning but not yet runnable.
        context: The services view this node needs, narrowed off the request
            context at dispatch. The default is the widest one.
    """

    node_type: str
    tier: NodeTier
    request: type["BaseRequest"]
    output: type["NodeWorkflowOutput"]
    executor: type["AppWorkflow"] | None = None
    input: type[WorkflowInput] = NodeInput
    context: type[RequestContext] = RequestContext

    def __post_init__(self) -> None:
        field = self.request.model_fields.get("node_type")
        declared = field.default if field is not None else None
        value = declared.value if isinstance(declared, Enum) else declared
        if value != self.node_type:
            raise ValueError(
                f"NodeSpec({self.node_type!r}) disagrees with "
                f"{self.request.__name__}.node_type default ({value!r}) — the "
                "planner emits the spec's name but pydantic discriminates on "
                "the schema's, so a mismatch makes the node unreachable"
            )
