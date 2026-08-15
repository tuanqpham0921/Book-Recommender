"""The live node registry — everything the planner and the task runner look up.

Each capability is a vertical slice exporting one `NodeSpec`; a domain's
`guide.py` lists its specs; this module collects them into `SPECS` and hands
that tuple to a single `Registry`. See `app/domains/README.md`.

The specs are the only state — request schema, executor, catalog entry and the
enum the planner emits under are all answered from that one indexed tuple, so
there are no parallel dicts to drift apart.

`make tools-catalog` renders this module rather than a checked-in snapshot.
"""

import inspect
import logging
from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Annotated, Union

from pydantic import Field

from app.domains.books.guide import BOOK_SPECS
from app.domains.node_spec import NodeSpec, NodeTier

logger = logging.getLogger(__name__)

# The planner hands back `NodeTypeEnum` members, internal code passes plain
# strings; every lookup accepts either, so no caller reaches for `.value`.
NodeTypeKey = str | Enum


class UnknownNodeTypeEnum(Enum):
    UNKNOWN = "unknown"


def class_docstring(cls: type) -> str:
    """A node's tool description. A free function because it reads only the
    class, and `evals/tools_catalog.py` calls it too."""
    docs = inspect.getdoc(cls)
    if not docs:
        return "No description"
    return docs.strip()


class Registry:
    """Every node lookup in the app, derived from a tuple of `NodeSpec`.

    Construction indexes the specs by `node_type` and rejects duplicates;
    everything else is a read over that index. Registration is also how a node
    is parked — a spec absent from the tuple has no catalog entry, no enum
    member and no executor, so the planner cannot target it.
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

        # Built once so the enum has one identity per process: a fresh Enum
        # produces members that fail `is` against the annotated ones.
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
        """The spec for a node type, or None — the "parked or hallucinated"
        answer callers branch on."""
        return self._by_node_type.get(self.key(node_type))

    def request(self, node_type: NodeTypeKey) -> type | None:
        """The request schema class, or None if the node type is unregistered."""
        spec = self.spec(node_type)
        return spec.request if spec else None

    def executor(self, node_type: NodeTypeKey) -> type | None:
        """The workflow that runs this node. None covers both "not registered"
        and "not yet runnable"; read `spec()` to tell those apart."""
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

        Flat rather than a union of each slice's label enum: a union renders as
        an anyOf of one-member enums — more tokens per node and a weaker
        constraint on the model.

        UNKNOWN is a member on purpose, so the LLM can decline instead of
        picking the nearest wrong capability; `planjane/executor.py` then
        refuses that one goal rather than failing the whole tool call.
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
        already checked. Derived on demand so it cannot drift from the specs.
        """
        return Annotated[
            Union[tuple(s.request for s in self.specs)],  # type: ignore[valid-type]
            Field(discriminator="node_type"),
        ]

    # ------------------------------------------------------------------
    # The capability catalog the planner reads

    def catalog_entries(self) -> dict[str, dict[str, str]]:
        """Structured capability catalog: tier label -> {node_type: description}.

        Walks `NodeTier` in declaration order, so prompt sections keep a stable
        order and every spec lands in exactly one of them. Empty tiers are
        dropped rather than rendered as an empty heading.
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

        Name on one line, description indented under it, so a long docstring
        stays visually attached instead of bleeding into the next entry.
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
# annotated with it at class-definition time. See `_build_node_type_enum`.
NodeTypeEnum = REGISTRY.node_type_enum


def main() -> None:
    print(REGISTRY.format_catalog())


if __name__ == "__main__":
    main()
