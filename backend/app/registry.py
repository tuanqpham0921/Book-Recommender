"""The live node registry — everything the planner and the task runner look up.

Nothing here is hand-maintained per node. Each capability is a vertical slice
under `app/domains/<domain>/<node>/` that exports one `NodeSpec`; a domain's
`guide.py` lists its specs; this module collects them into `SPECS` and hands
that tuple to a single `Registry`. Adding a capability means adding a folder
and one line in a guide — see `app/domains/README.md`.

**The specs are the only state.** Every question the app asks about a node —
its request schema, its executor, its catalog entry, the enum the planner emits
under — is answered by `Registry` from that one indexed tuple. There are no
parallel module-level dicts to keep in step, which is the drift this file used
to invite: `NODE_TYPE_TO_CLS`, `CATALOG_TIERS`, the tier class tuples and the
executor mapping each rebuilt the same spec relationship from a different
angle, so a node could be present in one and missing from another.

To see what the planner is actually told it can do right now, run
`make tools-catalog`: it renders this module, so it always reflects the live
state rather than a checked-in snapshot.
"""

import inspect
import logging
from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Annotated, Union

from pydantic import Field

from app.domains.books.guide import BOOK_SPECS
from app.domains.node_spec import NodeSpec, NodeTier
from app.domains.node_types import UnknownNodeTypeEnum

logger = logging.getLogger(__name__)

# Anything that names a node type. The planner hands back `NodeTypeEnum`
# members, tests and internal code pass the plain string. Every lookup accepts
# either, so no caller has to remember to reach for `.value` — forgetting it
# used to mean a silent miss against a str-keyed dict.
NodeTypeKey = str | Enum


def class_docstring(cls: type) -> str:
    """A node's tool description. Free function rather than a method: it reads
    only the class, and both the catalog and `evals/tools_catalog.py` call it
    on a request class they already hold."""
    docs = inspect.getdoc(cls)
    if not docs:
        return "No description"
    return docs.strip()


class Registry:
    """Every node lookup in the app, derived from a tuple of `NodeSpec`.

    Construction indexes the specs by `node_type` once and rejects duplicates;
    everything else is a read over that index. Nothing is cached that could go
    stale against the specs, and nothing is stored twice.

    Registration is also how a node is parked: a spec absent from the tuple has
    no catalog entry, no enum member and no executor, so the planner is never
    told about it and could not target it if it tried.
    """

    def __init__(self, specs: Iterable[NodeSpec]) -> None:
        self.specs: tuple[NodeSpec, ...] = tuple(specs)

        self._by_node_type: dict[str, NodeSpec] = {}
        for spec in self.specs:
            if spec.node_type in self._by_node_type:
                raise RuntimeError(
                    f"Duplicate node_type across domain guides: {spec.node_type!r}"
                )
            self._by_node_type[spec.node_type] = spec

        # Built once, at construction, so the enum has one identity for the
        # process: `SystemGoal.target_node_type` is annotated with it, and a
        # second call returning a fresh Enum would produce members that fail
        # `is` against the annotated ones.
        self.node_type_enum: type[Enum] = self._build_node_type_enum()

    # ------------------------------------------------------------------
    # Membership and iteration

    @staticmethod
    def key(node_type: NodeTypeKey) -> str:
        """Normalize an enum member or a string to the registered name."""
        return node_type.value if isinstance(node_type, Enum) else node_type

    def __contains__(self, node_type: object) -> bool:
        if not isinstance(node_type, (str, Enum)):
            return False
        return self.key(node_type) in self._by_node_type

    def __iter__(self) -> Iterator[NodeSpec]:
        return iter(self.specs)

    def __len__(self) -> int:
        return len(self.specs)

    @property
    def node_types(self) -> tuple[str, ...]:
        """The registered capability names, in guide order (= prompt order)."""
        return tuple(self._by_node_type)

    # ------------------------------------------------------------------
    # Spec lookups

    def spec(self, node_type: NodeTypeKey) -> NodeSpec | None:
        """The spec for a node type, or None when nothing is registered under
        that name — the "parked or hallucinated" answer callers branch on."""
        return self._by_node_type.get(self.key(node_type))

    def request(self, node_type: NodeTypeKey) -> type | None:
        """The request schema class, or None if the node type is unregistered."""
        spec = self.spec(node_type)
        return spec.request if spec else None

    def executor(self, node_type: NodeTypeKey) -> type | None:
        """The workflow that runs this node. None covers both "not registered"
        and "registered for planning but not yet runnable" — callers that need
        to tell those apart read `spec()` instead."""
        spec = self.spec(node_type)
        return spec.executor if spec else None

    def executors(self) -> tuple[type, ...]:
        """Every runnable executor class, deduplicated by registration order."""
        return tuple(s.executor for s in self.specs if s.executor is not None)

    def in_tier(self, tier: NodeTier) -> tuple[NodeSpec, ...]:
        return tuple(s for s in self.specs if s.tier is tier)

    # ------------------------------------------------------------------
    # What the planner is constrained by

    def _build_node_type_enum(self) -> type[Enum]:
        """The capability names the planner LLM may emit, as one flat enum.

        Built from the specs rather than unioning each slice's own label enum:
        a union renders as an anyOf of one-member enums in the JSON schema —
        more tokens per request with every node added, and a weaker constraint
        for the model than a single enum.

        UNKNOWN is a member on purpose. It lets the LLM say "no capability
        fits" instead of picking the nearest wrong one, and
        `planjane/executor.py` then refuses that one goal with a reason the
        user sees. Drop it and the same message becomes a hard pydantic error
        on the whole tool call, taking the other goals down with it.
        """
        return Enum(  # type: ignore[misc]
            "NodeTypeEnum",
            {
                **{s.node_type: s.node_type for s in self.specs},
                UnknownNodeTypeEnum.UNKNOWN.name: UnknownNodeTypeEnum.UNKNOWN.value,
            },
            type=str,
            module=__name__,
        )

    def request_union(self):
        """The registered request schemas as one discriminated union, for
        validating a tool call (or rehydrating a recorded plan) back into typed
        requests. Discriminated on `node_type`, whose Literal default `NodeSpec`
        already checked against the spec's name.

        Derived on demand rather than stored as a module constant: the old
        hand-listed union drifted out of step with the registered node types
        (docs/backlog.md), and a union built here cannot.
        """
        return Annotated[
            Union[tuple(s.request for s in self.specs)],  # type: ignore[valid-type]
            Field(discriminator="node_type"),
        ]

    # ------------------------------------------------------------------
    # The capability catalog the planner reads

    def catalog_entries(self) -> dict[str, dict[str, str]]:
        """Structured capability catalog: tier label -> {node_type: description}.

        Grouped by walking `NodeTier` in declaration order, so tier sections
        keep a stable order in the prompt and every spec lands in exactly one
        of them — `NodeSpec.tier` is typed as `NodeTier`, so the grouping is
        exhaustive by construction. Empty tiers are dropped rather than
        rendered as a heading with nothing under it.
        """
        entries: dict[str, dict[str, str]] = {}
        for tier in NodeTier:
            section = {
                spec.node_type: class_docstring(spec.request)
                for spec in self.in_tier(tier)
            }
            if section:
                entries[tier.value] = section
        return entries

    def format_catalog(self) -> str:
        """Render `catalog_entries()` as the prompt block the planner LLM sees.

        Each capability is its name on one line with the (possibly multi-line)
        description indented under it, so long docstrings stay visually
        attached to their name instead of bleeding into the next entry.
        """
        lines: list[str] = []
        for label, section in self.catalog_entries().items():
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
# The live registry — add a domain's guide to SPECS

SPECS: tuple[NodeSpec, ...] = BOOK_SPECS

REGISTRY = Registry(SPECS)

# Module-level because it is a *type*: `SystemGoal.target_node_type` is
# annotated with it at class-definition time, which is also why it must be one
# object rather than a per-call build. See `Registry._build_node_type_enum`.
NodeTypeEnum = REGISTRY.node_type_enum


def main() -> None:
    print(REGISTRY.format_catalog())


if __name__ == "__main__":
    main()
