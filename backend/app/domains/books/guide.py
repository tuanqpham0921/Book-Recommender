"""Book-domain guide: the specs of every node this domain offers.

One line per node — everything else (the node_type lookup, the catalog tiers,
the executor mapping, the request union) is derived from these in
`app/registry.py`, which composes this with the other domains' guides.

To park a node — keep the code, hide it from the planner — drop its SPEC from
BOOK_SPECS. The slice stays importable, but the planner never sees it in the
catalog and refuses any goal targeting it (parse_intent.py gates on
NODE_TYPE_TO_CLS membership). See docs/design/node-taxonomy-v1.md.
"""

from app.domains.books import analyze_recommend, find_by_title
from app.domains.node_spec import NodeSpec

BOOK_SPECS: tuple[NodeSpec, ...] = (
    find_by_title.SPEC,
    analyze_recommend.SPEC,
)
