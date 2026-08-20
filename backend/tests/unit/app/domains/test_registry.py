"""Tests for the node type registry (app/registry.py)."""
from app.registry import NODE_TYPE_TO_CLS, catalog_entries, format_node_type_catalog


class TestNodeToolDocstrings:
    """Node class docstrings become the tool descriptions the planner LLM
    sees (class_docstring / format_node_type_catalog) — a missing one
    silently degrades strategy selection."""

    def test_every_registered_node_has_its_own_docstring(self):
        # check cls.__doc__ directly, not inspect.getdoc(): getdoc inherits
        # through the MRO, so pydantic BaseModel's docstring would mask a
        # node class that forgot its own
        missing = [
            name for name, cls in NODE_TYPE_TO_CLS.items()
            if not (cls.__doc__ and cls.__doc__.strip())
        ]
        assert not missing, f"Node classes without docstrings: {missing}"

    def test_docstrings_are_substantial(self):
        # a placeholder like "TODO" exists but is useless as a tool description
        too_short = [
            name for name, cls in NODE_TYPE_TO_CLS.items()
            if len((cls.__doc__ or "").strip()) < 20
        ]
        assert not too_short, f"Node docstrings under 20 chars: {too_short}"

    def test_catalog_entries_cover_every_node_type_exactly_once(self):
        # a node type in two tiers would render twice in every parse prompt
        # and read as two different capabilities; one absent from all tiers
        # (and the "Other" fallback) would be invisible to the planner LLM
        seen: dict[str, str] = {}
        for tier, section in catalog_entries().items():
            for name in section:
                assert name not in seen, (
                    f"{name} appears in both {seen[name]!r} and {tier!r}"
                )
                seen[name] = tier
        assert set(seen) == set(NODE_TYPE_TO_CLS)

    def test_catalog_entries_have_names_and_descriptions(self):
        for tier, section in catalog_entries().items():
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
        catalog_lines = format_node_type_catalog().splitlines()
        for section in catalog_entries().values():
            for name, description in section.items():
                assert catalog_lines.count(name) == 1
                first_doc_line = description.splitlines()[0]
                assert catalog_lines[catalog_lines.index(name) + 1] == f"  {first_doc_line}"
