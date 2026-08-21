from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput

from .schemas import FindByCategoryArgs


class FindByCategoryInput(NodeInput):
    """The goal text and nothing else.

    The subject is read out of this node's own goal, so it has no field for
    upstream output — it *structurally* cannot consume one, which is the contract
    the empty subclass states. That absence is what separates this node from
    Filter_Retrieval, whose `anchors` is required: a subject with something to
    narrow is that node's job, a subject with nothing to narrow is this one's.
    """


class FindByCategoryOutput(BookRetrievalOutput):
    """`num_books` is how many books match the subject, `query` is how to reach them.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. That query is the point of
    this node — it is what lets Filter_Retrieval AND bounds onto a subject search
    and Combine_Intersect fold it together with an author's bibliography.

    The count is the honest report of a *lexical* match: these are books whose
    text contains the words, not books an embedding judged similar. `num_books ==
    0` is a real answer and the moment to try a broader word, not a failure.

    `args` is declared here rather than on `NodeWorkflowOutput`, and typed as the
    schema this node actually parses. None means the parse never happened, which
    is what `finalize_result` reads.
    """

    args: FindByCategoryArgs | None = None
