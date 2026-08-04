"""The live node registry — everything the planner and the task runner look up.

Nothing here is hand-maintained per node. Each capability is a vertical slice
under `app/domains/<domain>/<node>/` that exports one `NodeSpec`; a domain's
`guide.py` lists its specs; this module composes those into `SPECS` and derives
the rest. Adding a capability means adding a folder and one line in a guide —
see `app/domains/README.md`.

To see what the planner is actually told it can do right now, run
`make tools-catalog`: it renders this module, so it always reflects the live
state rather than a checked-in snapshot.
"""

import inspect
import logging
from enum import Enum
from typing import Annotated, Union

from pydantic import Field

logger = logging.getLogger(__name__)

from app.domains.books.guide import BOOK_SPECS
from app.domains.node_spec import NodeSpec, NodeTier
from app.domains.node_types import UnknownNodeTypeEnum
from playground.app_mock.executors.registry import MOCK_EXECUTORS_CLS_MAPPING

# -------------------------------------------------------------------
# All node specs — add a domain's guide here

SPECS: tuple[NodeSpec, ...] = BOOK_SPECS

_duplicates = {s.node_type for s in SPECS if [x.node_type for x in SPECS].count(s.node_type) > 1}
if _duplicates:
    raise RuntimeError(f"Duplicate node_type across domain guides: {sorted(_duplicates)}")


# -------------------------------------------------------------------
# DERIVED LOOKUPS — all of these used to be hand-maintained in parallel

# node_type name -> request schema class. The planner gates accepted goals on
# membership here (parse_intent.py), so this is also the "is it registered"
# check: a node absent from SPECS is unreachable, which is how a node is parked.
NODE_TYPE_TO_CLS: dict[str, type] = {s.node_type: s.request for s in SPECS}


def _requests_in(tier: NodeTier) -> tuple[type, ...]:
    return tuple(s.request for s in SPECS if s.tier is tier)


RETRIEVAL_CLASSES = _requests_in(NodeTier.RETRIEVAL)
ANALYZE_CLASSES = _requests_in(NodeTier.ANALYZE)
REQUEST_CLASSES = tuple(s.request for s in SPECS)

# The tool-call union the parsers validate against. Discriminated on node_type,
# whose Literal default NodeSpec already checked against the spec's name.
AnyStrategyRequest = Annotated[
    Union[REQUEST_CLASSES],  # type: ignore[valid-type]
    Field(discriminator="node_type"),
]

# The capability names the planner LLM may emit, as one flat enum. Built from
# SPECS rather than unioning each slice's own label enum: a union renders as an
# anyOf of one-member enums in the JSON schema — more tokens per request with
# every node added, and a weaker constraint for the model than a single enum.
#
# UNKNOWN is a member on purpose. It lets the LLM say "no capability fits"
# instead of picking the nearest wrong one, and parse_intent.py then refuses
# that goal with a reason the user sees. Drop it and the same message becomes a
# hard pydantic error on the whole tool call, taking the other goals with it.
NodeTypeEnum = Enum(  # type: ignore[misc]
    "NodeTypeEnum",
    {
        **{s.node_type: s.node_type for s in SPECS},
        UnknownNodeTypeEnum.UNKNOWN.name: UnknownNodeTypeEnum.UNKNOWN.value,
    },
    type=str,
    module=__name__,
)


def get_request_class(node_type: NodeTypeEnum | str) -> type:
    # isinstance instead of hasattr: same runtime behavior, narrows the type
    key = node_type.value if isinstance(node_type, Enum) else node_type
    return NODE_TYPE_TO_CLS[key]


def class_docstring(cls: type) -> str:
    docs = inspect.getdoc(cls)
    if not docs:
        return "No description"
    return docs.strip()


# Tier label -> request classes, in the order the tiers are declared on
# NodeTier. Kept as a plain dict because the playground extension below folds
# its own tiers in by mutating it.
CATALOG_TIERS: dict[str, tuple[type, ...]] = {
    tier.value: _requests_in(tier) for tier in NodeTier
}


def catalog_entries() -> dict[str, dict[str, str]]:
    """Structured capability catalog: tier label -> {node_type: description}.

    Every entry comes from NODE_TYPE_TO_CLS, so each node type appears exactly
    once with its registered name. Registered classes missing from every tier
    in CATALOG_TIERS fall into an "Other supported actions" section; a tier
    class that was never registered has no node_type name for the LLM to use,
    so it is skipped with a warning. Neither case can arise from a NodeSpec —
    both are reachable only through the playground extension, which still
    supplies raw class tuples.
    """
    cls_to_node_type = {cls: name for name, cls in NODE_TYPE_TO_CLS.items()}
    entries: dict[str, dict[str, str]] = {}
    listed: set[type] = set()

    for label, classes in CATALOG_TIERS.items():
        section: dict[str, str] = {}
        for cls in classes:
            name = cls_to_node_type.get(cls)
            if name is None:
                logger.warning(
                    f"{cls.__name__} is in catalog tier {label!r} but not in "
                    "NODE_TYPE_TO_CLS — skipped from the capability catalog"
                )
                continue
            section[name] = class_docstring(cls)
            listed.add(cls)
        if section:
            entries[label] = section

    extra = {
        name: class_docstring(cls)
        for name, cls in NODE_TYPE_TO_CLS.items()
        if cls not in listed
    }
    if extra:
        entries["Other supported actions"] = extra

    return entries


def format_node_type_catalog() -> str:
    """Render catalog_entries() as the prompt block the planner LLM sees.

    Each capability is its name on one line with the (possibly multi-line)
    description indented under it, so long docstrings stay visually attached
    to their name instead of bleeding into the next entry.
    """
    lines = []
    for label, section in catalog_entries().items():
        lines += ["", f"## {label}", ""]
        for name, description in section.items():
            lines.append(name)
            lines += [
                f"  {doc_line}" if doc_line.strip() else ""
                for doc_line in description.splitlines()
            ]
            lines.append("")
    if not lines:
        raise RuntimeError("Node type catalog is empty.")

    return "\n".join(lines).rstrip()


# -------------------------------------------------------------------
# EXECUTOR MAPPING

# The real executors, derived from the slices.
NODE_EXECUTORS_CLS_MAPPING: dict[type, type] = {
    s.request: s.executor for s in SPECS if s.executor is not None
}

# NOTE: temporary — the live mapping points at the mock executors under
# playground/app_mock, because the slice executors in
# app/domains/**/executor.py are still stubs that raise NotImplementedError.
# Flip this to NODE_EXECUTORS_CLS_MAPPING once they query the database.
EXECUTORS_CLS_MAPPING = MOCK_EXECUTORS_CLS_MAPPING


def main() -> None:
    print(format_node_type_catalog())


# # -------------------------------------------------------------------
# # PLAYGROUND EXTENSION — comment out this whole block to run with only the
# # app-registered node types above; nothing else in this file needs to change.
# # Folds the scalability-testing schemas from
# # playground/app_mock/extended_registry.py into the live planner registry.
# # Must run before the __main__ guard below, so `python -m app.registry`
# # reflects the same registry state everything else sees.
# #
# # CAVEAT (pre-dates the NodeSpec refactor): these classes arrive as raw
# # tuples, not specs, so they join the catalog and NODE_TYPE_TO_CLS but NOT
# # NodeTypeEnum — SystemGoal.target_node_type will reject a goal aimed at one.
# # Fine for measuring catalog size, which is what the toggle is for; give the
# # playground schemas real NodeSpecs before planning against them end to end.
# from playground.app_mock.extended_registry import (
#     ExtendedANALYZE_CLASSES,
#     ExtendedLIBRARY_CLASSES,
#     ExtendedNODE_TYPE_TO_CLS,
#     ExtendedRETRIEVAL_CLASSES,
# )

# RETRIEVAL_CLASSES = RETRIEVAL_CLASSES + ExtendedRETRIEVAL_CLASSES
# ANALYZE_CLASSES = ANALYZE_CLASSES + ExtendedANALYZE_CLASSES
# # ExtendedLIBRARY_CLASSES is neither retrieval nor analyze (read/write actions
# # on the user's shelf) — folded into REQUEST_CLASSES only, so it still counts
# # as a request class without joining either tier's class list
# REQUEST_CLASSES = RETRIEVAL_CLASSES + ANALYZE_CLASSES + ExtendedLIBRARY_CLASSES

# NODE_TYPE_TO_CLS.update(ExtendedNODE_TYPE_TO_CLS)
# CATALOG_TIERS[NodeTier.RETRIEVAL.value] = RETRIEVAL_CLASSES
# CATALOG_TIERS[NodeTier.ANALYZE.value] = ANALYZE_CLASSES


if __name__ == "__main__":
    main()
