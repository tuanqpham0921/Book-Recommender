from pydantic import Field

from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput


class CombineIntersectInput(NodeInput):
    """The results to AND together. Nothing else — this node parses no arguments.

    `min_length=2`, not 1, and the requirement is the node's contract: one input
    is not an intersection, and passing it through would report the upstream
    count as though something had narrowed it. `build_input` fills a `list[X]`
    with every match and a one-item list is still a *filled* field, so the
    length has to be rejected here — the runner then skips this one goal naming
    `anchors` rather than answering a wider question than was asked.

    Typed on the base, so any retrieval reaches it: an anchor
    (`Retrieve_by_Title`), a candidate (`Retrieve_by_Author`,
    `Retrieve_by_Lexical_Traits`, `Retrieve_by_Numeric_Traits`) or a similarity
    pool. That breadth is the point of the node — how a set was found stops
    mattering once it is a set.
    """

    anchors: list[BookRetrievalOutput] = Field(..., min_length=2)


class CombineIntersectOutput(BookRetrievalOutput):
    """`num_books` is what survived every condition, and `query` reaches exactly
    those books.

    Same shape as any retrieval — this node counts and hands on a query — but
    the query is the upstream ones ANDed together, so a downstream node composes
    against the intersection rather than re-applying anything. `num_books == 0`
    is a real answer: no book satisfied every condition at once, which is the
    moment to drop one rather than to fail the node.

    **On the base rather than either subclass, deliberately.** An intersection of
    two titles is anchor-shaped and an intersection of two subject searches is
    not, and the class cannot know which at definition time — so it lands on the
    base, which means "not anchorable" and is the safe half. The cost is that
    `Analyze_Similar_Books`, which requires `list[BookAnchorOutput]`, cannot
    depend on this node: "books like Harry Potter by Rowling" anchors on the
    title retrieval directly. See `BookRetrievalOutput`.

    No `args` field: this node has no parse to record. What it was asked is
    fully described by which goals it depended on.
    """
