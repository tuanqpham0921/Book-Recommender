"""Mermaid flowcharts from a neutral list of boxes.

The caller says what to draw — one `MermaidBox` per node with the ids it points
at — and this module owns how: id sanitization, label markup, edge emission and
orientation.

Nothing here knows about goals or any app type; its only import is `airglider`,
so this module travels wherever PlanJane travels. Turning goals into boxes is
the layer above (`dial/mermaid.py`).

Edges are declared as `sent_to`, the direction the arrow is drawn. Callers hold
the reverse (`depends_on`) and invert once when building boxes, so a box cannot
declare one arrow while the diagram emits another.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from airglider import remove_empty_values

WRAPPER_STYLE = "text-align:left"
HEADER_STYLE = "font-weight:bold;margin-bottom:8px"
ROW_STYLE = "margin-bottom:4px"


@dataclass(frozen=True)
class MermaidBox:
    """One node in a flowchart.

    Args:
        id: What other boxes name in their `sent_to`. Sanitized on the way out,
            so any string is safe. Should be unique — repeats are emitted as
            given, since which duplicate wins is the caller's decision.
        title: Bold header line. Omit for an unheaded box.
        body: The rest of the label. A mapping renders one `Key: value` row per
            entry (keys humanized, empties dropped, lists joined); a string
            renders as a single row.
        sent_to: Ids this box draws an arrow to. An id with no box is skipped
            rather than conjuring an empty node beside the graph.
    """

    id: str
    title: str = ""
    body: str | Mapping[str, Any] | None = None
    sent_to: Sequence[str] = ()


def clean_string_mermaid(text: str) -> str:
    """Strip the characters that would terminate or corrupt a node label."""
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)


def mermaid_id(raw_id: str) -> str:
    """Sanitize an id into a Mermaid node identifier."""
    return re.sub(r"[^\w]", "_", raw_id)


def _format_field_name(key: str) -> str:
    return key.replace("_", " ").title()


def _format_label_row(label: str, value: str) -> str:
    prefix = f"<strong>{label}:</strong> " if label else ""
    return f"<div style='{ROW_STYLE}'>{prefix}{clean_string_mermaid(value)}</div>"


def _body_rows(body: str | Mapping[str, Any] | None) -> list[str]:
    if not body:
        return []
    if isinstance(body, str):
        return [_format_label_row("", body)]

    rows = []
    for key, value in remove_empty_values(dict(body)).items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        rows.append(_format_label_row(_format_field_name(str(key)), str(value)))
    return rows


def format_box_label(box: MermaidBox) -> str:
    """The HTML label for one box: bold title, then one row per body entry."""
    rows = [f"<div style='{WRAPPER_STYLE}'>"]
    if box.title:
        rows.append(
            f"<div style='{HEADER_STYLE}'>{clean_string_mermaid(box.title)}</div>"
        )
    rows += _body_rows(box.body)
    rows.append("</div>")
    return "".join(rows)


def choose_orientation(levels: Mapping[str, int] | None) -> str:
    """TD for wide/concurrent graphs, LR for deep/sequential dependency
    chains — ties (including the no-levels/single-node default) favor TD."""
    if not levels:
        return "TD"
    depth = max(levels.values()) + 1
    width = max(Counter(levels.values()).values())
    return "TD" if width >= depth else "LR"


def levels_from_boxes(boxes: Sequence[MermaidBox]) -> dict[str, int]:
    """Longest-path depth per box id, used only to orient the diagram.

    One past the deepest predecessor. Arrows at ids with no box count as
    nothing, and a visit guard breaks cycles so an invalid graph still renders.
    """
    incoming: dict[str, list[str]] = {box.id: [] for box in boxes}
    for box in boxes:
        for target in box.sent_to:
            if target in incoming:
                incoming[target].append(box.id)

    levels: dict[str, int] = {}

    def depth(box_id: str, seen: frozenset[str]) -> int:
        if box_id in levels:
            return levels[box_id]
        preds = [pred for pred in incoming[box_id] if pred not in seen]
        levels[box_id] = 1 + max(
            (depth(pred, seen | {box_id}) for pred in preds), default=-1
        )
        return levels[box_id]

    for box_id in incoming:
        depth(box_id, frozenset())
    return levels


def get_diagram(
    boxes: Sequence[MermaidBox], *, orientation: str | None = None
) -> str | None:
    """Render `boxes` as a Mermaid flowchart, or None when there is nothing to
    draw — every caller treats that as skip-this-step. Orientation comes from
    the graph's own shape unless one is passed."""
    if not boxes:
        return None

    known = {box.id for box in boxes}
    if orientation is None:
        orientation = choose_orientation(levels_from_boxes(boxes))

    lines = [f"flowchart {orientation}"]
    lines += [f'\t{mermaid_id(box.id)}["{format_box_label(box)}"]' for box in boxes]
    lines += [
        f"\t{mermaid_id(box.id)} --> {mermaid_id(target)}"
        for box in boxes
        for target in box.sent_to
        if target in known
    ]

    return "\n".join(lines) + "\n"
