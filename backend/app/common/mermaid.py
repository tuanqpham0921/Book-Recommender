import re

from app.domains.base_request import BaseRequest

def clean_string_mermaid(text: str) -> str:
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)


def mermaid_id(raw_id: str) -> str:
    """Sanitize task ids for Mermaid node identifiers."""
    return re.sub(r"[^\w]", "_", raw_id)


def get_mermaid_diagram(
    execution_order: list[str], id_to_node: dict[str, BaseRequest]
) -> str:
    
    lines = ["flowchart LR"]

    for task in execution_order:
        node = id_to_node[task]
        node_id = mermaid_id(task)
        label = clean_string_mermaid(task)
        lines.append(f'\t{node_id}["{task}: {node.node_type.value}"]')

    for task in execution_order:
        node = id_to_node[task]
        if not hasattr(node, "depends_on"):
            continue
        for dep in node.depends_on:
            lines.append(f"\t{mermaid_id(dep)} --> {task}")

    return "\n".join(lines) + "\n"
