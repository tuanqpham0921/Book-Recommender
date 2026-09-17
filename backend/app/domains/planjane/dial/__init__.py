"""dial — how PlanJane shows a plan.

The plan's instrument face: `mermaid.py` turns goals into boxes, `format.py`
turns boxes into a Mermaid string. Rendering the plan belongs to the planner
because the diagram *is* the plan rendered, and it lives in its own subpackage
because it is the one part of PlanJane with no dependency on the rest of the
app — `format.py` imports only `airglider`, `mermaid.py` adds nothing beyond
it. That is deliberate: PlanJane is headed for being a service of its own, and
this is the corner already free to travel.

Import from here, not from the modules — the split between "what a box says"
and "how a box is drawn" is an internal one.
"""

from .format import MermaidBox, get_diagram
from .mermaid import get_goals_mermaid_diagram

__all__ = [
    "get_goals_mermaid_diagram",
    "MermaidBox",
    "get_diagram",
]
