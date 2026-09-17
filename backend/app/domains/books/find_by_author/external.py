from app.domains.books.external import BookCandidateOutput
from app.domains.node_input import NodeInput

from .schemas import FindByAuthorArgs


class FindByAuthorInput(NodeInput):
    """The goal text and nothing else.

    Retrieval is single-dimension and reads the author out of its own goal, so
    this node has no field for upstream output — it *structurally* cannot
    consume one, which is the contract the empty subclass states. An artifact
    routed here would be logged as unclaimed by `build_input` rather than
    silently shaping the query.
    """


class FindByAuthorOutput(BookCandidateOutput):
    """`num_books` is how many books that author has here, `query` is how to
    reach them.

    A **candidate** set, and the closest call of the three: a name is specific,
    so a short bibliography would fold into an anchor perfectly well. The node
    is on this side because it cannot tell which it returned — twelve Herberts
    fold, eight hundred Kings do not — so "books like Frank Herbert's" is served
    by describing the taste, not by anchoring on the shelf.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. `num_books == 0` means the
    catalog carries nothing by that author — a real answer, and the moment to
    ask the user for a different name rather than to fail the node. It is also
    the honest half of an authorship check: Combine_Intersect over this node and
    Retrieve_by_Title answers "did X write Y?" with an empty set.

    `args` is declared here rather than on `NodeWorkflowOutput`, and typed as
    the schema this node actually parses: what "the arguments" *are* is a fact
    about one node, so the base has no useful annotation for it. None means the
    parse never happened, which is what `finalize_result` reads."""

    args: FindByAuthorArgs | None = None
