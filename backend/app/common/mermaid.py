import re
from typing import TYPE_CHECKING

from app.common.base_node import BaseNode

if TYPE_CHECKING:
    from app.orchestration.planner.task_planner import TaskPlan

def clean_string_mermaid(text):
    # Remove parentheses, quotes, and Mermaid-reserved symbols
    return re.sub(r'[()"\'<>{}\[\]|`#%@:;\\/]', "", text)

def get_mermaid_diagram(task_plan: "TaskPlan", node_ids: dict[str, BaseNode]) -> str:
    accepted_ids = set(task.id for task in task_plan.accepted)
    
    def is_retrieval_node(node_id: str) -> bool:
        return node_id.endswith(("_tit", "_isbn", "_traits"))
    
    def is_analyze_node(node_id: str) -> bool:
        return node_id.endswith(("_cmp", "_rec"))

    result = "flowchart LR\n"

    # Retrieval subgraph
    
    retrieval_nodes, analyze_nodes = [], []
    for id in node_ids:
        if id not in accepted_ids:
            continue
        
        description = clean_string_mermaid(node_ids[id].description)
        if is_retrieval_node(id) and id:
            retrieval_nodes.append(f"\t\t{id}[{description}]")
        elif is_analyze_node(id):
            analyze_nodes.append(f"\t\t{id}[{description}]")
        
    result += "\n\tsubgraph Retrieval\n\t\tdirection LR\n"
    result += "\n".join(retrieval_nodes) + "\n\t\tend\n"
    # Analyze subgraph  
    result += "\n\tsubgraph Analyze\n\t\tdirection LR\n"
    result += "\n".join(analyze_nodes) + "\n\t\tend\n"

    # Dependencies
    result += "\n\tRetrieval ~~~ Analyze\n"
    for task in task_plan.accepted:
        for depends_on in task.depends_on:
            result += f"\t{depends_on} ---> {task.id}\n"

    return result