"""Book-domain guide: the specs of every node this domain offers.

One line per node; `Registry` (app/registry.py) answers everything else from
these. To park a node — keep the code, hide it from the planner — drop its SPEC
here: the slice stays importable, but the planner never sees it and
`planjane/executor.py` refuses any goal targeting it. See
docs/design/node-taxonomy-v1.md.
"""

from app.domains.books import (
    analyze_recommend,
    filter_books,
    find_by_author,
    find_by_title,
)
from app.domains.node_spec import NodeSpec

BOOK_SPECS: tuple[NodeSpec, ...] = (
    find_by_title.SPEC,
    find_by_author.SPEC,
    filter_books.SPEC,
    analyze_recommend.SPEC,
)
