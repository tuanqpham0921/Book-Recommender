"""Tests for the tool-catalog report's pure parts.

Unlike the other two reports, this one reads the live registry rather than the
database, so `collect_tools`/`summarize` are tested against a small fake tier
map instead of a fixture table — asserting on the real registry would make
these tests fail every time a node is added, which is the opposite of useful.
The registry-shaped assertions that *are* worth pinning live in
tests/unit/app/domains/test_registry.py.
"""

from datetime import datetime, timezone

import pytest

import evals.tools_catalog as tools_catalog
from evals.tools_catalog import (
    build_audit,
    build_report,
    count_tokens,
    get_encoder,
    missing_sections,
    prompt_costs,
    purpose_line,
    render_catalog_entry,
    summarize,
    table_cell,
)


@pytest.fixture
def encoder():
    return get_encoder("gpt-4.1")


def make_tool(node_type="Retrieve_by_Thing", **overrides):
    tool = {
        "node_type": node_type,
        "tier": "Retrieval — lookup or fetch data",
        "tier_short": "Retrieval",
        "cls": "FindByThing",
        "purpose": "Retrieve a thing.",
        "catalog_tokens": 100,
        "schema_tokens": 400,
        "chars": 500,
        "has_executor": True,
        "missing_sections": [],
    }
    tool.update(overrides)
    return tool


class TestGetEncoder:
    def test_falls_back_for_models_tiktoken_does_not_know(self):
        # tiktoken 0.9 raises KeyError for gpt-4.1/gpt-5 — the exact models
        # this project runs, so the fallback is the normal path, not an edge
        assert get_encoder("gpt-4.1").name == "o200k_base"

    def test_unknown_model_name_still_returns_an_encoder(self):
        assert get_encoder("not-a-real-model-9000").name == "o200k_base"


class TestRenderCatalogEntry:
    def test_matches_the_registry_renderer_shape(self):
        # the name on its own line, description indented two spaces under it
        out = render_catalog_entry("Retrieve_by_Thing", "Purpose: x.\nArgs: y.")

        assert out == "Retrieve_by_Thing\n  Purpose: x.\n  Args: y."

    def test_blank_lines_stay_blank_rather_than_becoming_indent(self):
        # trailing whitespace on an otherwise empty line would be billed
        out = render_catalog_entry("Node", "a\n\nb")

        assert out.splitlines()[2] == ""

    def test_the_real_renderer_still_produces_this_shape(self):
        # guards the duplication: if Registry.format_catalog changes how it
        # indents, per-tool token counts silently stop matching the prompt
        from app.registry import REGISTRY, class_docstring

        name = REGISTRY.node_types[0]
        entry = render_catalog_entry(name, class_docstring(REGISTRY.request(name)))

        assert entry in REGISTRY.format_catalog()


class TestMissingSections:
    def test_complete_docstring_has_nothing_missing(self):
        doc = "".join(f"{s} x\n" for s in tools_catalog.EXPECTED_SECTIONS)

        assert missing_sections(doc + "Example queries: x\n") == []

    def test_example_values_satisfy_the_examples_requirement(self):
        doc = "".join(f"{s} x\n" for s in tools_catalog.EXPECTED_SECTIONS)

        assert missing_sections(doc + "Example genres: fiction, mystery\n") == []
        assert missing_sections(doc + "Example semantic_input: cozy\n") == []

    def test_reports_each_absent_section(self):
        assert missing_sections("Purpose: do a thing.") == [
            "Args:",
            "Returns:",
            "depends_on:",
            "Use when:",
            "Do not use:",
            "Constraints:",
            "Example queries:",
        ]


class TestPurposeLine:
    def test_extracts_the_purpose_section(self):
        doc = "Purpose: Retrieve a book by title.\n\nArgs:\n    title: the title."

        assert purpose_line(doc) == "Retrieve a book by title."

    def test_falls_back_to_the_first_line_without_the_convention(self):
        # a docstring that skips Purpose: still shows something in the column;
        # flagging it as malformed is the audit section's job, not this one's
        assert purpose_line("Does a thing.\n\nArgs: x") == "Does a thing."

    def test_finds_purpose_even_when_it_is_not_first(self):
        assert purpose_line("Some preamble.\nPurpose: The real one.") == "The real one."

    def test_empty_docstring_yields_empty_string(self):
        assert purpose_line("") == ""
        assert purpose_line("\n\n  \n") == ""


class TestTableCell:
    def test_escapes_pipes(self):
        # an unescaped pipe splits the row and silently shifts every numeric
        # column after it — the failure looks like wrong data, not bad markup
        assert table_cell("a | b") == "a \\| b"

    def test_collapses_newlines(self):
        assert "\n" not in table_cell("line one\nline two")

    def test_truncates_long_text(self):
        out = table_cell("x" * 500, limit=20)

        assert len(out) <= 21  # 20 + the ellipsis
        assert out.endswith("…")


class TestSummarize:
    def test_counts_tools_per_tier(self, encoder):
        tools = [
            make_tool("A"),
            make_tool("B"),
            make_tool("C", tier_short="Analyze"),
        ]

        stats = summarize(tools, "some catalog text", encoder)

        assert stats["tools"] == 3
        assert stats["per_tier"] == {"Retrieval": 2, "Analyze": 1}

    def test_block_tokens_come_from_the_rendered_text_not_the_sum(self, encoder):
        # tier headings and blank lines are billed too, so the block is the
        # honest figure and the per-tool sum is always the smaller one
        tools = [make_tool("A", catalog_tokens=1)]

        stats = summarize(tools, "## A tier heading\n\nand some body text", encoder)

        assert stats["sum_tool_tokens"] == 1
        assert stats["block_tokens"] > stats["sum_tool_tokens"]

    def test_flags_tools_without_executors(self, encoder):
        tools = [make_tool("A"), make_tool("B", has_executor=False)]

        assert summarize(tools, "", encoder)["no_executor"] == ["B"]

    def test_flags_incomplete_docstrings(self, encoder):
        tools = [make_tool("A"), make_tool("B", missing_sections=["Do not use:"])]

        assert summarize(tools, "", encoder)["undocumented"] == ["B"]

    def test_unschemad_tool_does_not_break_the_total(self, encoder):
        # schema_tokens is None when pydantic_function_tool refuses the class
        tools = [make_tool("A", schema_tokens=None), make_tool("B", schema_tokens=10)]

        assert summarize(tools, "", encoder)["schema_tokens_total"] == 10


class TestPromptCosts:
    def test_one_row_per_consuming_call_site(self):
        costs = prompt_costs(1000)

        assert len(costs) == len(tools_catalog.CATALOG_CONSUMERS)
        assert {c["model"] for c in costs} == {
            model for model, _, _ in tools_catalog.CATALOG_CONSUMERS
        }

    def test_cached_is_cheaper_than_uncached(self):
        # the whole reason both are reported: the catalog is byte-identical
        # every request, so the cached rate is the steady state
        for cost in prompt_costs(1000):
            assert cost["cached"] < cost["uncached"]

    def test_cost_scales_with_catalog_size(self):
        small = sum(c["uncached"] for c in prompt_costs(1000))
        large = sum(c["uncached"] for c in prompt_costs(2000))

        assert large == pytest.approx(small * 2)

    def test_unpriced_model_yields_none_not_zero(self, monkeypatch):
        # matches airglider/src/config.py: unknown spend must never render as free
        monkeypatch.setattr(
            tools_catalog, "CATALOG_CONSUMERS", (("gpt-9-omega", 1, "somewhere"),)
        )

        assert prompt_costs(1000)[0]["uncached"] is None


class TestBuildAudit:
    def test_clean_catalog_says_so(self):
        stats = {"no_executor": [], "undocumented": []}

        assert "Nothing to flag." in "\n".join(build_audit([make_tool()], stats))

    def test_missing_executor_is_called_out(self):
        stats = {"no_executor": ["Analyze_Compare"], "undocumented": []}

        out = "\n".join(build_audit([make_tool()], stats))

        assert "No executor" in out
        assert "`Analyze_Compare`" in out

    def test_incomplete_docstring_is_called_out(self):
        tools = [make_tool("A", missing_sections=["Example queries:"])]
        stats = {"no_executor": [], "undocumented": ["A"]}

        out = "\n".join(build_audit(tools, stats))

        assert "`Example queries:`" in out
        assert "Nothing to flag." not in out


class TestBuildReport:
    """End-to-end against the real registry — asserting on structure and
    invariants only, never on a node count or a token total, so adding a node
    doesn't break the test."""

    @pytest.fixture
    def report(self):
        return build_report(
            "abc1234", datetime(2026, 7, 21, tzinfo=timezone.utc), "gpt-4.1"
        )

    def test_has_the_expected_sections(self, report):
        for heading in ("# Planner Tool Catalog", "## Summary", "## Cost per request",
                        "## Tools", "## Audit"):
            assert heading in report

    def test_stamps_provenance(self, report):
        assert "abc1234" in report
        assert "2026-07-21" in report
        assert "o200k_base" in report

    def test_lists_every_registered_node(self, report):
        from app.registry import REGISTRY

        for name in REGISTRY.node_types:
            assert f"`{name}`" in report

    def test_reports_a_nonzero_cost(self, report):
        # a $0.000000 total would mean the pricing lookup silently missed
        assert "$0.000000" not in report.split("## Tools")[0]

    def test_every_tool_row_carries_a_purpose(self, report):
        from app.registry import REGISTRY, class_docstring

        for spec in REGISTRY:
            name = spec.node_type
            purpose = purpose_line(class_docstring(spec.request))
            assert purpose, f"{name} has no purpose line"
            # the head survives truncation even for the longest descriptions
            assert purpose[:40] in report, f"{name}'s purpose is missing from the table"

    def test_table_rows_have_a_consistent_column_count(self, report):
        # guards the pipe escaping: one unescaped pipe in a docstring would
        # give that row extra columns and misalign its numbers
        table = report.split("## Tools")[1].split("## Audit")[0]
        rows = [line for line in table.splitlines() if line.startswith("|")]
        widths = {row.count("|") - row.count("\\|") for row in rows}

        assert len(widths) == 1, f"ragged tool table: {widths}"
