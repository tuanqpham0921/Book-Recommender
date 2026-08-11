"""What a unit of work is invoked *with* — the typed half of the call.

`RequestContext` (app/common/request_context.py) answers "what can I reach";
this answers "what am I working on". A node declares its input as a subclass
and lists it on its `NodeSpec`, and `build_input` assembles it from the goal
text plus whatever the nodes before it produced.

**The declaration is the point, not the typing.** `dict[str, Any]` can tell a
node that something is missing, but never *what* — so a node short of an anchor
could only raise. A named, empty field is enough to say which slot is empty and
what shape would fill it, which is the seam an agentic node needs to ask the
planner for one. That is also why fields here should default rather than be
required whenever the node has a real fallback: a required field is for input a
node genuinely cannot proceed without.

Fields are filled by **type, never by name** — the rule the old
`AppWorkflow.find_artifact` followed, lifted out of the node bodies into
`build_input` so it is written once. A key in `artifacts` is provenance.

This module imports nothing from the rest of `app/domains/` on purpose:
`base_workflow` imports *it*, to annotate the one call shape.
"""

import logging
from collections.abc import Mapping
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class WorkflowInput(BaseModel):
    """Base for every call payload.

    Carries nothing. A pipeline step whose work is driven entirely by one
    artifact — `TaskRunnerInput`, which takes a plan — has no query to speak
    of, and handing it an unused one would make the field a lie.
    """

    # a field may hold a DeferredBookQuery or another arbitrary payload that
    # travelled on an upstream output
    model_config = ConfigDict(arbitrary_types_allowed=True)


class NodeInput(WorkflowInput):
    """What a *dispatchable capability* is invoked with.

    `query` is universal for nodes and required: the user's text at the top of
    a turn, the goal description the planner wrote further down. A node's job
    is then always the same — parse it, reject it, or continue with it.
    """

    query: str


def _resolve(annotation: Any, available: list[Any]) -> tuple[bool, Any]:
    """`(filled, value)` for one field, matched against the artifacts by type.

    `filled=False` means nothing matched *and* the field has no None to stand
    in for it — it is then left out of the model entirely, so pydantic's own
    required-field error names it. That error is the "what is missing" answer;
    a second mechanism to report it would only be one more thing to keep in
    step.
    """
    origin, args = get_origin(annotation), get_args(annotation)

    # list[X] — every match, and an empty list is a legitimate answer
    if origin is list and args:
        return True, [a for a in available if isinstance(a, args[0])]

    # X | None — the first match, or None
    if origin in (Union, UnionType):
        wanted = tuple(a for a in args if isinstance(a, type) and a is not type(None))
        found = next((a for a in available if isinstance(a, wanted)), None) if wanted else None
        return found is not None, found

    # X — the first match; absent means unfilled
    if isinstance(annotation, type):
        found = next((a for a in available if isinstance(a, annotation)), None)
        return found is not None, found

    return False, None


def build_input(
    input_cls: type[WorkflowInput],
    query: str,
    artifacts: Mapping[str, Any],
) -> WorkflowInput:
    """Assemble a node's declared input from the goal text and its
    dependencies' outputs.

    Raises `pydantic.ValidationError` when a required field cannot be filled.
    The dispatch site catches it, so an input that can't be assembled fails
    that one goal rather than the whole plan.
    """
    available = list(artifacts.values())
    claimed: set[int] = set()
    values: dict[str, Any] = {}

    for name, field in input_cls.model_fields.items():
        if name == "query":
            values["query"] = query
            continue

        filled, value = _resolve(field.annotation, available)
        if not filled:
            continue

        values[name] = value
        for item in value if isinstance(value, list) else [value]:
            claimed.add(id(item))

    # Not an error: a node is free to ignore an upstream output, and pooling
    # several dependencies onto one field is normal. Logged because "the plan
    # fed this node something it has no slot for" is usually a planning bug.
    unclaimed = [
        f"{key}: {type(value).__name__}"
        for key, value in artifacts.items()
        if id(value) not in claimed
    ]
    if unclaimed:
        logger.debug(f"{input_cls.__name__} has no field for: {unclaimed}")

    return input_cls(**values)
