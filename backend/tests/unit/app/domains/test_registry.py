"""Tests for the node type registry (app/registry.py)."""
import pytest

from app.domains.node_spec import NodeSpec, NodeTier
from app.registry import REGISTRY, Registry


class TestNodeToolDocstrings:
    """Node class docstrings become the tool descriptions the planner LLM
    sees (class_docstring / Registry.format_catalog) — a missing one
    silently degrades strategy selection."""

    def test_every_registered_node_has_its_own_docstring(self):
        # check cls.__doc__ directly, not inspect.getdoc(): getdoc inherits
        # through the MRO, so pydantic BaseModel's docstring would mask a
        # node class that forgot its own
        missing = [
            spec.node_type for spec in REGISTRY
            if not (spec.request.__doc__ and spec.request.__doc__.strip())
        ]
        assert not missing, f"Node classes without docstrings: {missing}"

    def test_docstrings_are_substantial(self):
        # a placeholder like "TODO" exists but is useless as a tool description
        too_short = [
            spec.node_type for spec in REGISTRY
            if len((spec.request.__doc__ or "").strip()) < 20
        ]
        assert not too_short, f"Node docstrings under 20 chars: {too_short}"

    def test_catalog_entries_cover_every_node_type_exactly_once(self):
        # a node type in two tiers would render twice in every parse prompt
        # and read as two different capabilities; one absent from all tiers
        # would be invisible to the planner LLM
        seen: dict[str, str] = {}
        for tier, section in REGISTRY.catalog_entries().items():
            for name in section:
                assert name not in seen, (
                    f"{name} appears in both {seen[name]!r} and {tier!r}"
                )
                seen[name] = tier
        assert set(seen) == set(REGISTRY.node_types)

    def test_catalog_entries_have_names_and_descriptions(self):
        for tier, section in REGISTRY.catalog_entries().items():
            assert tier.strip(), "catalog tier with a blank label"
            assert section, f"catalog tier {tier!r} rendered with no entries"
            for name, description in section.items():
                assert name.strip(), f"blank node type name in tier {tier!r}"
                assert description != "No description", f"{name} has no docstring"
                assert len(description.strip()) >= 20, f"{name} description too short"

    def test_formatted_catalog_renders_every_entry(self):
        # the prompt block is built from catalog_entries — every structured
        # entry must survive rendering, once: the name as its own line, the
        # description indented under it
        catalog_lines = REGISTRY.format_catalog().splitlines()
        for section in REGISTRY.catalog_entries().values():
            for name, description in section.items():
                assert catalog_lines.count(name) == 1
                first_doc_line = description.splitlines()[0]
                assert catalog_lines[catalog_lines.index(name) + 1] == f"  {first_doc_line}"


class TestRegistryLookups:
    """The lookups replaced the parallel dicts this module used to export, so
    they carry the invariants those dicts were relied on for."""

    def test_lookups_accept_a_string_or_an_enum_member(self):
        # the planner hands back NodeTypeEnum members; internal code and the
        # eval report pass plain strings. Both must resolve to the same spec.
        name = REGISTRY.node_types[0]
        member = REGISTRY.node_type_enum(name)

        assert REGISTRY.spec(member) is REGISTRY.spec(name)
        assert member in REGISTRY and name in REGISTRY

    def test_unregistered_node_type_resolves_to_none_everywhere(self):
        # planjane gates on membership and task_runner branches on spec(),
        # so an unregistered name has to be answerable rather than raise
        assert "Not_A_Node" not in REGISTRY
        assert REGISTRY.spec("Not_A_Node") is None
        assert REGISTRY.request("Not_A_Node") is None
        assert REGISTRY.executor("Not_A_Node") is None

    def test_every_spec_is_reachable_by_its_node_type(self):
        for spec in REGISTRY:
            assert REGISTRY.spec(spec.node_type) is spec
            assert REGISTRY.request(spec.node_type) is spec.request
            assert REGISTRY.executor(spec.node_type) is spec.executor
        assert len(REGISTRY) == len(REGISTRY.node_types)

    def test_tiers_partition_the_specs(self):
        # what makes catalog_entries exhaustive without an "other" bucket
        tiered = [spec for tier in NodeTier for spec in REGISTRY.in_tier(tier)]

        assert sorted(s.node_type for s in tiered) == sorted(REGISTRY.node_types)

    def test_executors_lists_only_runnable_nodes(self):
        assert set(REGISTRY.executors()) == {
            s.executor for s in REGISTRY if s.executor is not None
        }

    def test_node_type_enum_has_one_identity(self):
        # SystemGoal.target_node_type is annotated with it at class-definition
        # time; a per-call rebuild would give members that fail `is`
        assert REGISTRY.node_type_enum is REGISTRY.node_type_enum

    def test_node_type_enum_covers_the_specs_plus_unknown(self):
        assert {m.value for m in REGISTRY.node_type_enum} == {
            *REGISTRY.node_types,
            "unknown",
        }


class TestRegistryConstruction:
    def test_duplicate_node_types_are_rejected(self):
        # two guides listing the same name would make one node silently
        # shadow the other in every lookup
        spec = REGISTRY.specs[0]

        with pytest.raises(RuntimeError, match="Duplicate node_type"):
            Registry([spec, spec])

    def test_empty_registry_refuses_to_render_a_catalog(self):
        # an empty prompt block would ship a planner with no tools at all
        with pytest.raises(RuntimeError, match="catalog is empty"):
            Registry([]).format_catalog()

    def test_a_registry_is_independent_of_the_live_one(self):
        # registration is how a node is parked — a smaller spec tuple must
        # produce a smaller registry, not read through to REGISTRY
        one = Registry([REGISTRY.specs[0]])

        assert len(one) == 1
        assert isinstance(one.specs[0], NodeSpec)
