from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput

from .schemas import FindByNumericTraitsArgs


class FindByNumericTraitsInput(NodeInput):
    """The goal text and nothing else.

    The bounds are read out of this node's own goal, so it has no field for
    upstream output — it *structurally* cannot consume one, which is the
    contract the empty subclass states. That absence is also what separates this
    node from Filter_Retrieval, whose `anchors` is required: bounds with
    something to narrow are that node's job, bounds with nothing to narrow are
    this one's, and neither can be handed the other's input by accident.
    """


class FindByNumericTraitsOutput(BookRetrievalOutput):
    """`num_books` is how many books sit inside the bounds, `query` is how to
    reach them.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. The count carries more
    weight here than on the other retrievals — bounds inferred from words can be
    far looser or far tighter than the user pictured ("well rated" is 2,190 books;
    "recent" is 29), so the number beside the phrase is how they find that out.
    `num_books == 0` is a real answer, and the moment to loosen a bound rather
    than to fail the node.

    `args` is declared here rather than on `NodeWorkflowOutput`, and typed as
    the schema this node actually parses: what "the arguments" *are* is a fact
    about one node, so the base has no useful annotation for it. None means the
    parse never happened, which is what `finalize_result` reads."""

    args: FindByNumericTraitsArgs | None = None
