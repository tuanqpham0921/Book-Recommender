"""Tests for planjane/dial/format.py — the Mermaid renderer.

Boxes in, diagram string out. No app types appear anywhere in this file, and
that is the point being pinned: the renderer's only import is airglider, so it
travels with PlanJane. The layer that turns goals into boxes is tested next
door, in test_mermaid.py.
"""

from app.domains.planjane.dial.format import (
    MermaidBox,
    choose_orientation,
    clean_string_mermaid,
    format_box_label,
    get_diagram,
    levels_from_boxes,
    mermaid_id,
)


def box(box_id, sent_to=(), title="T", body=None):
    return MermaidBox(id=box_id, title=title, body=body, sent_to=sent_to)


def edges(diagram: str) -> list[str]:
    return sorted(line.strip() for line in diagram.splitlines() if "-->" in line)


class TestCleanStringMermaid:
    def test_removes_special_chars(self):
        raw = 'Hello (world) "test" [bracket] {brace} <angle>'
        result = clean_string_mermaid(raw)
        for char in '()"[]{}<>':
            assert char not in result

    def test_preserves_alphanumeric(self):
        result = clean_string_mermaid("Hello World 123")
        assert "Hello" in result and "World" in result and "123" in result

    def test_empty_string_stays_empty(self):
        assert clean_string_mermaid("") == ""


class TestMermaidId:
    def test_replaces_hyphens(self):
        assert "-" not in mermaid_id("task-abc")

    def test_keeps_underscores_and_alphanum(self):
        assert mermaid_id("task_a1b2c3d4") == "task_a1b2c3d4"

    def test_replaces_dots(self):
        assert "." not in mermaid_id("task.1")


class TestFormatBoxLabel:
    def test_title_renders_as_a_bold_header(self):
        assert "<strong>" not in format_box_label(box("1", title="Retrieve"))
        assert "Retrieve" in format_box_label(box("1", title="Retrieve"))

    def test_mapping_body_renders_one_labelled_row_per_entry(self):
        label = format_box_label(box("1", body={"task": "1", "title": "Dune"}))

        assert "<strong>Task:</strong> 1" in label
        assert "<strong>Title:</strong> Dune" in label

    def test_body_keys_are_humanized(self):
        assert "Num Books" in format_box_label(box("1", body={"num_books": 3}))

    def test_string_body_renders_unlabelled(self):
        label = format_box_label(box("1", body="just some text"))

        assert "just some text" in label
        assert "<strong>" not in label

    def test_empty_body_values_are_dropped(self):
        label = format_box_label(box("1", body={"kept": "x", "gone": None, "e": ""}))

        assert "Kept" in label
        assert "Gone" not in label

    def test_list_values_are_joined(self):
        assert "a, b" in format_box_label(box("1", body={"tags": ["a", "b"]}))

    def test_label_special_chars_are_stripped(self):
        # an unescaped quote or bracket would terminate the Mermaid label
        label = format_box_label(box("1", title='He said "hi"', body={"k": "[x]"}))

        assert '"' not in label
        assert "[x]" not in label

    def test_untitled_box_renders_only_its_body(self):
        assert "font-weight:bold" not in format_box_label(
            box("1", title="", body={"k": "v"})
        )


class TestGetDiagram:
    def test_no_boxes_returns_none(self):
        assert get_diagram([]) is None

    def test_starts_with_a_flowchart_header(self):
        assert get_diagram([box("1")]).startswith("flowchart ")

    def test_emits_one_node_per_box(self):
        diagram = get_diagram([box("task_1"), box("task_2")])

        assert "task_1[" in diagram and "task_2[" in diagram

    def test_draws_an_arrow_in_the_sent_to_direction(self):
        # a --sent_to--> b must emit `a --> b`, not the reverse
        diagram = get_diagram([box("a", sent_to=["b"]), box("b")])

        assert edges(diagram) == ["a --> b"]

    def test_independent_boxes_have_no_edges(self):
        assert "-->" not in get_diagram([box("1"), box("2")])

    def test_arrows_to_unknown_ids_are_dropped(self):
        # a dangling target would render as an empty mystery node beside the
        # graph — worse than no edge at all
        diagram = get_diagram([box("a", sent_to=["nope"])])

        assert "-->" not in diagram
        assert "nope" not in diagram

    def test_ids_are_sanitized_in_both_nodes_and_edges(self):
        diagram = get_diagram([box("a.1", sent_to=["b-2"]), box("b-2")])

        assert "a.1" not in diagram and "b-2" not in diagram
        assert edges(diagram) == ["a_1 --> b_2"]

    def test_explicit_orientation_overrides_the_computed_one(self):
        assert get_diagram([box("1")], orientation="LR").startswith("flowchart LR")

    def test_wide_graph_orients_td(self):
        boxes = [box("a"), box("b"), box("c")]

        assert get_diagram(boxes).startswith("flowchart TD")

    def test_deep_chain_orients_lr(self):
        boxes = [box("a", sent_to=["b"]), box("b", sent_to=["c"]), box("c")]

        assert get_diagram(boxes).startswith("flowchart LR")

    def test_a_cycle_renders_rather_than_hanging(self):
        # an invalid graph is still better drawn than hung on
        boxes = [box("a", sent_to=["b"]), box("b", sent_to=["a"])]

        assert get_diagram(boxes).startswith("flowchart")


class TestLevelsFromBoxes:
    def test_roots_are_level_zero(self):
        assert levels_from_boxes([box("a"), box("b")]) == {"a": 0, "b": 0}

    def test_depth_is_one_past_the_deepest_predecessor(self):
        boxes = [box("a", sent_to=["c"]), box("b", sent_to=["c"]), box("c")]

        assert levels_from_boxes(boxes)["c"] == 1

    def test_arrows_from_unknown_ids_do_not_deepen_a_box(self):
        assert levels_from_boxes([box("a", sent_to=["ghost"])]) == {"a": 0}


class TestChooseOrientation:
    def test_no_levels_defaults_to_td(self):
        assert choose_orientation(None) == "TD"
        assert choose_orientation({}) == "TD"

    def test_wide_shallow_graph_is_td(self):
        assert choose_orientation({"a": 0, "b": 0, "c": 0}) == "TD"

    def test_narrow_deep_graph_is_lr(self):
        assert choose_orientation({"a": 0, "b": 1, "c": 2}) == "LR"

    def test_tie_favors_td(self):
        assert choose_orientation({"a": 0}) == "TD"
