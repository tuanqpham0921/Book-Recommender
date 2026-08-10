"""Goals → `MermaidBox`es. The drawing itself is `dial/format.py`.

This module decides only what a box *says* — which field heads it, which
fields earn a row — and hands the boxes to `get_diagram`, which owns markup,
orientation and emission. Splitting there is what keeps the renderer free of
app types.

**PlanJane owns the whole mermaid stack**, hence `planjane/dial/` rather than
somewhere shared: the diagram *is* the plan rendered, so a caller that drew it
would be doing the planner's job. It is also the direction PlanJane is headed —
a service of its own — and drawing the plan has to travel with it. Today
PlanJane is the only thing in the app that formats a diagram at all.

**The `depends_on` → `sent_to` inversion happens here, once.** Goals record who
must run before them; Mermaid draws arrows the other way. Doing it in one place
means no call site can get the arrow backwards.
"""

from collections.abc import Mapping
from typing import Any

from airglider import remove_empty_values, to_serializable

from .format import MermaidBox, get_diagram

# Rendered as the "Task"/"Goal" row instead, so the raw field would duplicate it.
SKIP_LABEL_KEYS = {"id"}


def _to_boxes(nodes: Mapping[str, Any], label_for) -> list[MermaidBox]:
    """One box per node, with `depends_on` inverted into `sent_to`.

    Kept generic over "things with an id and a depends_on" rather than typed to
    `SystemGoal`: that is the whole of what a diagram needs from a node, and it
    is what let the parsed-request diagram share this code before it was
    retired.

    A dependency on an id that isn't in `nodes` — a goal the planner refused,
    say — contributes no edge. `get_diagram` would drop it anyway; dropping it
    here keeps the box's own declaration honest.
    """
    sent_to: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for dep in getattr(node, "depends_on", []) or []:
            if dep in sent_to:
                sent_to[dep].append(node_id)

    boxes = []
    for node_id, node in nodes.items():
        title, body = label_for(node_id, node)
        boxes.append(
            MermaidBox(id=node_id, title=title, body=body, sent_to=tuple(sent_to[node_id]))
        )
    return boxes


def _goal_label(node_id: str, goal: Any) -> tuple[str, dict[str, Any]]:
    """A goal box: the capability it targets as the header, then its id,
    description and reasoning."""
    data = remove_empty_values(to_serializable(goal))
    title = str(data.get("target_node_type") or data.get("node_type") or "Goal")
    return title, {
        "Goal": node_id,
        "Description": data.get("description"),
        "Reasoning": data.get("reasoning"),
    }


def get_goals_mermaid_diagram(goals: list) -> str | None:
    """Flowchart of the planner's system goals — one box per goal, headed by
    the capability it targets, with edges drawn from each goal's depends_on."""
    return get_diagram(_to_boxes({goal.id: goal for goal in goals}, _goal_label))