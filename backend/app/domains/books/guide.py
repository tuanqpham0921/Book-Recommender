"""Book-domain guide: the specs of every node this domain offers.

One line per node; `Registry` (app/registry.py) answers everything else from
these. To park a node — keep the code, hide it from the planner — drop its SPEC
here: the slice stays importable, but the planner never sees it and
`planjane/executor.py` refuses any goal targeting it. See
docs/design/node-taxonomy-v1.md.
"""

from app.domains.books import (
    find_by_author,
    find_by_lexical_traits,
    find_by_numeric_traits,
    find_by_title,
    find_similar_books,
    intersect_books,
    write_recommendations,
)
from app.domains.node_spec import NodeSpec

# `intersect_books` (Combine_Intersect) registered 2026-08-24, replacing the
# `filter_books` (Filter_Retrieval) slice that was parked 2026-08-22 and is now
# deleted: bounds are a retrieval (`find_by_numeric_traits`) and combining them
# with a subject is this node's job, so the two ways of expressing a bound
# collapsed into one. See docs/design/node-taxonomy-v1.md.
BOOK_SPECS: tuple[NodeSpec, ...] = (
    find_by_title.SPEC,
    find_by_author.SPEC,
    find_by_lexical_traits.SPEC,
    find_by_numeric_traits.SPEC,
    find_similar_books.SPEC,
    intersect_books.SPEC,
    # `write_recommendations` (Generate_Recommendations) registered 2026-09-07:
    # the first NodeTier.GENERATE slice — the planner ends every recommendation
    # chain with it. See docs/design/execution-pipeline-v1.md.
    write_recommendations.SPEC,
)
