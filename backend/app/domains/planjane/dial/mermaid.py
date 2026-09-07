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
from dataclasses import replace
from typing import Any

from airglider import remove_empty_values, to_serializable

from .format import MermaidBox, get_diagram

logger = logging.getLogger(__name__)

# Rendered as the "Task"/"Goal" row instead, so the raw field would duplicate it.
SKIP_LABEL_KEYS = {"id"}

ANSWER_ID_PREFIX = "answer_"
ANSWER_BOX_TITLE = "Answer"
ANSWER_BOX_BODY = "Written from everything this branch found"


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


def _with_answer_boxes(boxes: list[MermaidBox]) -> list[MermaidBox]:
    """Append one answer box per sink, and point each sink at its own.

    The answer stage is not a goal. The planner never chose it and it has no
    catalog entry — the task runner attaches one to every sink of the plan. But
    it is part of what the turn will do, so the plan the user is shown says so.

    A sink here is a box that sends to nothing, which is the same "nothing
    depends on this" that `ExecutionOrder.sinks` computes, read off the already
    inverted edges. The two are separate because `dial/` imports nothing from
    `app/` — it travels with PlanJane — so it cannot ask the plan and reads the
    graph it was handed instead.

    No sinks means every box points somewhere, i.e. a cycle: nothing to hang an
    answer off, and the goal diagram is drawn as-is.
    """
    sinks = [box for box in boxes if not box.sent_to]
    if not sinks:
        return boxes

    answers: list[MermaidBox] = []
    rewired: dict[str, MermaidBox] = {}
    for index, sink in enumerate(sinks, start=1):
        answer_id = f"{ANSWER_ID_PREFIX}{index}"
        # frozen dataclass — a new box with the one arrow added
        rewired[sink.id] = replace(sink, sent_to=(answer_id,))
        answers.append(
            MermaidBox(
                id=answer_id, title=ANSWER_BOX_TITLE, body=ANSWER_BOX_BODY
            )
        )

    return [rewired.get(box.id, box) for box in boxes] + answers


def get_goals_mermaid_diagram(goals: list) -> str | None:
    """Flowchart of the planner's system goals — one box per goal, headed by
    the capability it targets, with edges drawn from each goal's depends_on,
    plus the answer each branch of the plan ends in."""
    try:
        boxes = _to_boxes({goal.id: goal for goal in goals}, _goal_label)
        return get_diagram(_with_answer_boxes(boxes))
    except Exception as e:
        logger.warning(f"Error generating Mermaid diagram: {e}")
        return None
