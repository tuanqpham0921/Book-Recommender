"""What a unit of work is invoked *with* — the typed half of the call.

`RequestContext` answers "what can I reach"; this answers "what am I working
on". A node declares its input as a subclass and lists it on its `NodeSpec`;
`build_input` assembles it from the planner's instruction plus what ran before
it.

The declaration is the point, not the typing. A `dict[str, Any]` can say
something is missing but never *what*; a named, empty field says which slot is
empty and what shape would fill it — the seam an agentic node needs to ask the
planner for one. So default a field whenever the node has a real fallback, and
require it only when the node cannot proceed without it.

Fields are filled by type, never by name — a key in `artifacts` is provenance.

Imports nothing else from `app/domains/`: `base_workflow` imports *it*.
"""

import logging
from collections.abc import Mapping
from types import UnionType
from typing import Any, Generic, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class WorkflowInput(BaseModel):
    """Base for every call payload. Carries nothing: a step driven entirely by
    one artifact (`TaskRunnerInput`) has no instruction, and handing it an
    unused one would make the field a lie."""

    # a field may hold a DeferredBookQuery or another arbitrary payload that
    # travelled on an upstream output
    model_config = ConfigDict(arbitrary_types_allowed=True)


class NodeInput(WorkflowInput):
    """What a dispatchable capability is invoked with. `instruction` is
    universal and required, and it means the same thing at both heights of the
    turn: the text this unit of work is to act on. At the top it is the user's
    own message (`Orchestrator` → `Triage` → `PlanJane`); below the planner it
    is that goal's `SystemGoal.instruction`.

    For a node it is the *only* thing it is told about the ask — no node reads
    `ctx.user_message`, which is why the goal text is shipped to an argument
    parser as an `AssistantMessage` rather than as a user turn. The one
    exception is the generation node, which reads the user's message
    deliberately, as the untrusted half of a trust split.

    Named for what it is rather than `query`, which in this codebase already
    means a `DeferredBookQuery` on every book-shaped output.
    """

    instruction: str

ParsedT = TypeVar("ParsedT", bound=BaseModel)


class ParsedInput(WorkflowInput, Generic[ParsedT]):
    """The other end of a node's entry: arguments someone already parsed.

    A node reached from natural language takes a `NodeInput` and does its own
    tool call; a node reached as an already-filled tool schema takes this and
    skips straight to the processing. Parameterized by the schema the node
    parses into (`ParsedInput[GoalParseRequest]`), so the branch inside the
    executor is a typed field rather than a cast.
    """

    parsed_result: ParsedT

def _resolve(annotation: Any, available: list[Any]) -> tuple[bool, Any]:
    """`(filled, value)` for one field, matched against the artifacts by type.

    `filled=False` means nothing matched and no None can stand in, so the field
    is left out of the model entirely and pydantic's own required-field error
    names it — that error is the "what is missing" answer.
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
    instruction: str,
    artifacts: Mapping[str, Any],
) -> WorkflowInput:
    """Assemble a node's declared input from the planner's instruction and its
    dependencies' outputs.

    Raises `pydantic.ValidationError` when a required field cannot be filled;
    the dispatch site catches it, so that one goal fails rather than the plan.
    """
    available = list(artifacts.values())
    claimed: set[int] = set()
    values: dict[str, Any] = {}

    for name, field in input_cls.model_fields.items():
        if name == "instruction":
            values["instruction"] = instruction
            continue

        filled, value = _resolve(field.annotation, available)
        if not filled:
            continue

        values[name] = value
        for item in value if isinstance(value, list) else [value]:
            claimed.add(id(item))

    # Not an error — a node may ignore an upstream output — but logged,
    # because a node with no slot for what it was fed is usually a planning bug.
    unclaimed = [
        f"{key}: {type(value).__name__}"
        for key, value in artifacts.items()
        if id(value) not in claimed
    ]
    if unclaimed:
        logger.debug(f"{input_cls.__name__} has no field for: {unclaimed}")

    return input_cls(**values)
