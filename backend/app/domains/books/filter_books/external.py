from pydantic import Field

from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput

from .schemas import FilterRetrieval


class FilterRetrievalInput(NodeInput):
    """What to narrow, plus the goal text the bounds are read out of.

    `anchors` is the one required dependency field in the domain, and the
    requirement is the node's contract: bounds with nothing to bound are the
    "no subject" case the request docstring sends back for clarification, so
    there is no fallback to fall back to. `min_length=1` is what makes that
    fail: `build_input` fills a `list[X]` with every match and an empty list is
    still a filled field, so the emptiness has to be rejected here — the runner
    then skips this one goal naming `anchors` rather than running a filter over
    the whole catalog.
    """

    anchors: list[BookRetrievalOutput] = Field(..., min_length=1)


class FilterRetrievalOutput(BookRetrievalOutput):
    """`num_books` is what survived the bounds, and `query` reaches exactly
    those books.

    Same shape as any retrieval — this node counts and hands on a query — but
    the query it hands on is the upstream one with the bounds ANDed into it, so
    a downstream node composes against the narrowed set rather than re-applying
    the filter. `num_books == 0` is a real answer: the bounds excluded
    everything the depended-on step found, which is the moment to loosen them
    rather than to fail the node.
    """

    args: FilterRetrieval | None = None
