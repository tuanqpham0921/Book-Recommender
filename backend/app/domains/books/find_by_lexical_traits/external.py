from app.domains.books.external import BookCandidateOutput
from app.domains.node_input import NodeInput

from .schemas import FindByLexicalTraitsArgs


class FindByLexicalTraitsInput(NodeInput):
    """The goal text and nothing else.

    The traits are read out of this node's own goal, so it has no field for
    upstream output — it *structurally* cannot consume one, which is the contract
    the empty subclass states. That absence is what separates this node from
    Combine_Intersect, whose `anchors` is required: this node contributes a set,
    that one combines sets, and neither can be handed the other's input by
    accident.
    """


class FindByLexicalTraitsOutput(BookCandidateOutput):
    """`num_books` is how many books match the traits, `query` is how to reach them.

    A **candidate** set, and the clearest case for the split: "mystery" matches
    358 books, and folding 358 blurbs into one description of an ideal book
    describes nothing at all. A lexical ask is served by embedding the words
    themselves, not by anchoring on what those words happened to match.

    The node keeps no rows: it streams a few cards so the section has something
    in it, and what it hands downstream is the query. That query is the point of
    this node — it is what lets Combine_Intersect AND it together with an
    author's bibliography or a page-count bound.

    The count is the honest report of a *lexical* match: these are books whose
    text contains the words, not books an embedding judged similar. `num_books ==
    0` is a real answer and the moment to try a broader word, not a failure.

    `args` is declared here rather than on `NodeWorkflowOutput`, and typed as the
    schema this node actually parses. None means the parse never happened, which
    is what `finalize_result` reads.
    """

    args: FindByLexicalTraitsArgs | None = None
