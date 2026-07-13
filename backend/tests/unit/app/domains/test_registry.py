"""Tests for the node type registry (app/registry.py)."""
from app.registry import NODE_TYPE_TO_CLS, format_node_type_catalog


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

    def test_catalog_lists_every_node_type_without_fallback(self):
        catalog = format_node_type_catalog()
        unlisted = [
            name for name in NODE_TYPE_TO_CLS if f"- {name}:" not in catalog
        ]
        assert not unlisted, f"Node types missing from catalog: {unlisted}"
        assert "No description" not in catalog

    def test_catalog_lists_every_node_type_exactly_once(self):
        # the "Other supported actions" section is only for registered classes
        # missing from both tier lists — a node type appearing twice bloats
        # every parse prompt and reads as two different capabilities
        catalog = format_node_type_catalog()
        duplicated = [
            name for name in NODE_TYPE_TO_CLS
            if catalog.count(f"- {name}:") != 1
        ]
        assert not duplicated, f"Node types listed more than once: {duplicated}"
