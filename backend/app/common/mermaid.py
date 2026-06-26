import re

from app.domains.base_request import BaseRequest
from common.utils import to_jsonable

SKIP_LABEL_KEYS = {"id"}


def clean_string_mermaid(text: str) -> str:
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)


def mermaid_id(raw_id: str) -> str:
    """Sanitize task ids for Mermaid node identifiers."""
    return re.sub(r"[^\w]", "_", raw_id)


def format_node_label(task_id: str, data: dict) -> str:
    lines = [task_id]
    for key, value in data.items():
        if key.startswith("_") or key in SKIP_LABEL_KEYS or value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            value = ", ".join(str(item) for item in value)
        lines.append(f"{key}: {clean_string_mermaid(str(value))}")
    return "<br/>".join(lines)


def get_mermaid_diagram(
    execution_order: list[str], id_to_node: dict[str, BaseRequest]
) -> str:
    lines = ["flowchart LR"]

    for task in execution_order:
        node = id_to_node[task]
        node_id = mermaid_id(task)
        label = format_node_label(task, to_jsonable(node))
        lines.append(f'\t{node_id}["<div style="text-align:left">{label}</div>"]')

    for task in execution_order:
        node = id_to_node[task]
        if not hasattr(node, "depends_on"):
            continue
        for dep in node.depends_on:
            lines.append(f"\t{mermaid_id(dep)} --> {mermaid_id(task)}")

    return "\n".join(lines) + "\n"
