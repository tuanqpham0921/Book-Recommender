import re

from app.domains.base_request import BaseRequest
from common.utils import to_jsonable

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
    node_type = clean_string_mermaid(str(data.get("node_type", "")))
    rows = [
        f"<div style='{WRAPPER_STYLE}'>",
        f"<div style='{HEADER_STYLE}'>{node_type}</div>",
        _format_label_row("Task", task_id),
    ]

    for key, value in data.items():
        if key.startswith("_") or key in SKIP_LABEL_KEYS or value is None:
            continue
        if key == "node_type":
            continue
        if isinstance(value, list):
            if not value:
                continue
            value = ", ".join(str(item) for item in value)
        rows.append(_format_label_row(_format_field_name(key), str(value)))

    rows.append("</div>")
    return "".join(rows)


def get_mermaid_diagram(
    execution_order: list[str], id_to_node: dict[str, BaseRequest]
) -> str:
    lines = ["flowchart LR"]

    for task in execution_order:
        node = id_to_node[task]
        node_id = mermaid_id(task)
        label = format_node_label(task, to_jsonable(node))
        lines.append(f'\t{node_id}["{label}"]')

    for task in execution_order:
        node = id_to_node[task]
        if not hasattr(node, "depends_on"):
            continue
        for dep in node.depends_on:
            lines.append(f"\t{mermaid_id(dep)} --> {mermaid_id(task)}")

    return "\n".join(lines) + "\n"
