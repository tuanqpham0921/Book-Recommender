"""Goals → `MermaidBox`es. The drawing itself is `dial/format.py`.

This module decides only what a box *says*; `get_diagram` owns markup,
orientation and emission, which is what keeps the renderer free of app types.

PlanJane owns the whole mermaid stack — the diagram *is* the plan rendered, so a
caller that drew it would be doing the planner's job, and it has to travel with
PlanJane when that becomes its own service.

The `depends_on` → `sent_to` inversion happens here, once, so no call site can
get the arrow backwards.
"""
import logging
from collections.abc import Mapping
from typing import Any

from airglider import remove_empty_values, to_serializable

from .format import MermaidBox, get_diagram

logger = logging.getLogger(__name__)

# Rendered as the "Task"/"Goal" row instead, so the raw field would duplicate it.
SKIP_LABEL_KEYS = {"id"}


def _to_boxes(nodes: Mapping[str, Any], label_for) -> list[MermaidBox]:
    """One box per node, with `depends_on` inverted into `sent_to`.

    Generic over "things with an id and a depends_on" rather than typed to
    `SystemGoal` — that is all a diagram needs from a node.

    A dependency on an id not in `nodes` (a refused goal) contributes no edge.
    `get_diagram` would drop it anyway; dropping it here keeps the box honest.
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
    try:
        return get_diagram(_to_boxes({goal.id: goal for goal in goals}, _goal_label))
    except Exception as e:
        logger.warning(f"Error generating Mermaid diagram: {e}")
        return None
