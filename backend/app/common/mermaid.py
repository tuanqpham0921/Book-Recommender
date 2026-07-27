import re
from collections import Counter
from collections.abc import Mapping

from app.domains.base_request import BaseRequest
from common.utils import to_serializable, remove_empty_values

SKIP_LABEL_KEYS = {"id"}

WRAPPER_STYLE = "text-align:left"
HEADER_STYLE = "font-weight:bold;margin-bottom:8px"
ROW_STYLE = "margin-bottom:4px"


def clean_string_mermaid(text: str) -> str:
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)


def mermaid_id(raw_id: str) -> str:
    """Sanitize task ids for Mermaid node identifiers."""
    return re.sub(r"[^\w]", "_", raw_id)


def _format_label_row(label: str, value: str) -> str:
    return (
        f"<div style='{ROW_STYLE}'>"
        f"<strong>{label}:</strong> {clean_string_mermaid(value)}"
        f"</div>"
    )


def _format_field_name(key: str) -> str:
    return key.replace("_", " ").title()


def format_node_label(task_id: str, data: dict) -> str:
    cleaned = remove_empty_values(data)
    node_type = clean_string_mermaid(str(cleaned.get("node_type", "")))
    rows = [
        f"<div style='{WRAPPER_STYLE}'>",
        f"<div style='{HEADER_STYLE}'>{node_type}</div>",
        _format_label_row("Task", task_id),
    ]

    for key, value in cleaned.items():
        if key.startswith("_") or key in SKIP_LABEL_KEYS or key == "node_type":
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        rows.append(_format_label_row(_format_field_name(key), str(value)))

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


def get_mermaid_diagram(
    execution_order: list[str],
    id_to_node: Mapping[str, BaseRequest],
    levels: Mapping[str, int] | None = None,
) -> str | None:
    lines = [f"flowchart {choose_orientation(levels)}"]

    for task in execution_order:
        node = id_to_node[task]
        node_id = mermaid_id(task)
        label = format_node_label(task, to_serializable(node))
        lines.append(f'\t{node_id}["{label}"]')

    for task in execution_order:
        node = id_to_node[task]
        # get_depends_on returns [] for nodes without dependencies
        for dep in node.get_depends_on():
            lines.append(f"\t{mermaid_id(dep)} --> {mermaid_id(task)}")

    if len(lines) == 1:
        return None

    return "\n".join(lines) + "\n"


def _dependency_levels(id_to_node: Mapping[str, "object"]) -> dict[str, int]:
    """Longest-path depth per node id, used only to orient the diagram.

    A node's level is one past its deepest in-plan dependency; deps that point
    outside the plan count as roots. A visit guard breaks any cycle (invalid
    plans that the planner should already reject) so this never recurses forever.
    """
    levels: dict[str, int] = {}

    def depth(gid: str, seen: frozenset[str]) -> int:
        if gid in levels:
            return levels[gid]
        node = id_to_node.get(gid)
        deps = [
            d
            for d in (getattr(node, "depends_on", []) or [])
            if d in id_to_node and d not in seen
        ]
        lvl = 1 + max((depth(d, seen | {gid}) for d in deps), default=-1)
        levels[gid] = lvl
        return lvl

    for gid in id_to_node:
        depth(gid, frozenset())
    return levels


def _format_goal_label(goal: "object") -> str:
    """Box label for one system goal: the capability it targets as the header,
    then the goal id and its normalized description."""
    data = remove_empty_values(to_serializable(goal))
    capability = clean_string_mermaid(str(data.get("target_node_type") or "Goal"))
    rows = [
        f"<div style='{WRAPPER_STYLE}'>",
        f"<div style='{HEADER_STYLE}'>{capability}</div>",
        _format_label_row("Goal", str(data.get("id", ""))),
    ]
    description = data.get("description")
    if description:
        rows.append(_format_label_row("Description", str(description)))
    reasoning = data.get("reasoning")
    if description:
        rows.append(_format_label_row("Reasoning", str(reasoning)))
    rows.append("</div>")
    return "".join(rows)


def _render_flowchart(id_to_node: Mapping[str, "object"], label_for) -> str | None:
    """Node + edge emission shared by the goal- and argument-level diagrams.

    Both key their nodes by id and draw edges from depends_on, so they differ
    only in how a single box is labelled — which is what label_for supplies.
    """
    levels = _dependency_levels(id_to_node)
    lines = [f"flowchart {choose_orientation(levels)}"]

    for node_id, node in id_to_node.items():
        lines.append(f'\t{mermaid_id(node_id)}["{label_for(node_id, node)}"]')

    for node_id, node in id_to_node.items():
        for dep in getattr(node, "depends_on", []) or []:
            lines.append(f"\t{mermaid_id(dep)} --> {mermaid_id(node_id)}")

    if len(lines) == 1:
        return None

    return "\n".join(lines) + "\n"


def get_goals_mermaid_diagram(goals: list) -> str | None:
    """Flowchart of the planner's system goals — one box per goal headed by the
    capability it targets, with edges drawn from each goal's depends_on.

    This is the goal-level counterpart to get_mermaid_diagram (which renders
    typed task requests). Goals carry id/depends_on/target_node_type directly,
    so no execution order or node lookup is needed from the caller.
    """
    return _render_flowchart(
        {goal.id: goal for goal in goals},
        lambda _gid, goal: _format_goal_label(goal),
    )


def get_parsed_mermaid_diagram(requests: list) -> str | None:
    """Flowchart of the argument parser's output — the same shape as
    get_goals_mermaid_diagram, because each request inherits its goal's id and
    depends_on, but each box shows the typed arguments the parser filled in
    instead of the goal's description.

    Requests the parser never stamped with an id are dropped: without one they
    have no place in the graph and would collide under a shared None key.
    """
    return _render_flowchart(
        {req.id: req for req in requests if req.id},
        lambda req_id, req: format_node_label(req_id, to_serializable(req)),
    )
