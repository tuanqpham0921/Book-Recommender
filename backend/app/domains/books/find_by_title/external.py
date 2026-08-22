from app.domains.books.external import BookAnchorOutput
from app.domains.node_input import NodeInput

from .schemas import FindByTitleArgs


class FindByTitleInput(NodeInput):
    """The goal text and nothing else.

    Retrieval is single-dimension and reads the title out of its own goal, so
    this node has no field for upstream output — it *structurally* cannot
    consume one, which is the contract the empty subclass states. An artifact
    routed here would be logged as unclaimed by `build_input` rather than
    silently shaping the query.
    """


class FindByTitleOutput(BookAnchorOutput):
    """`num_books` is how many titles matched and `query` is how to reach them.

    An **anchor** rather than a candidate set, and this is the node the
    distinction is drawn around: the user named a book, so the match can be
    folded into a description of what to look for next. That is what
    `BookAnchorOutput` claims, and it is a claim about the *ask* — a title
    search can still return six editions of the same book, so a consumer that
    folds them keeps its own cap.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. `num_books == 0` means the
    catalog has no such title — a real answer, and the moment to ask the user for
    a better one rather than to fail the node.

    `args` is declared here rather than on `NodeWorkflowOutput`, and typed as
    the schema this node actually parses: what "the arguments" *are* is a fact
    about one node, so the base has no useful annotation for it. None means the
    parse never happened, which is what `finalize_result` reads."""

    args: FindByTitleArgs | None = None
