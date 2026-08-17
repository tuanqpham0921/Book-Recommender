from app.domains.books.external import BookRetrievalOutput
from app.domains.node_input import NodeInput


class FindByTitleInput(NodeInput):
    """The goal text and nothing else.

    Retrieval is single-dimension and reads the title out of its own goal, so
    this node has no field for upstream output — it *structurally* cannot
    consume one, which is the contract the empty subclass states. An artifact
    routed here would be logged as unclaimed by `build_input` rather than
    silently shaping the query.
    """


class FindByTitleOutput(BookRetrievalOutput):
    """`num_books` is how many titles matched and `query` is how to reach them.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. `num_books == 0` means the
    catalog has no such title — a real answer, and the moment to ask the user for
    a better one rather than to fail the node."""
