import re
from typing import TYPE_CHECKING

from app.domains.base_request import BaseRequest

if TYPE_CHECKING:
    from app.orchestration.planner.task_planner import TaskPlan


def clean_string_mermaid(text: str) -> str:
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)


def mermaid_id(raw_id: str) -> str:
    """Sanitize task ids for Mermaid node identifiers."""
    return re.sub(r"[^\w]", "_", raw_id)


def get_mermaid_diagram(task_plan: "TaskPlan", node_ids: dict[str, BaseRequest]) -> str:
    lines = ["flowchart LR"]

    for task in task_plan.accepted:
        node = node_ids[task.id]
        node_id = mermaid_id(task.id)
        label = clean_string_mermaid(node.id)
        lines.append(f'\t{node_id}["{task.id}: {node.node_type.value}"]')

    for task in task_plan.accepted:

        for dep in task.depends_on:
            lines.append(f"\t{mermaid_id(dep)} --> {task.id}")

    return "\n".join(lines) + "\n"
