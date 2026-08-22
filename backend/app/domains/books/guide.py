"""Book-domain guide: the specs of every node this domain offers.

One line per node; `Registry` (app/registry.py) answers everything else from
these. To park a node — keep the code, hide it from the planner — drop its SPEC
here: the slice stays importable, but the planner never sees it and
`planjane/executor.py` refuses any goal targeting it. See
docs/design/node-taxonomy-v1.md.
"""

from app.domains.books import (
    find_by_author,
    find_by_category,
    find_by_numeric_traits,
    find_by_title,
    find_similar_books,
)
from app.domains.node_spec import NodeSpec

# Parked 2026-08-22: `filter_books` (Filter_Retrieval). The slice stays
# importable and tested — `describe_bounds` still comes from it, for
# `find_by_numeric_traits` — it is only absent from the catalog, so the planner
# cannot target it. Unparking is re-adding the import and the SPEC line. What
# that costs is recorded in docs/design/node-taxonomy-v1.md.
BOOK_SPECS: tuple[NodeSpec, ...] = (
    find_by_title.SPEC,
    find_by_author.SPEC,
    find_by_category.SPEC,
    find_by_numeric_traits.SPEC,
    find_similar_books.SPEC,
)
