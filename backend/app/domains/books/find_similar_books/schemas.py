from typing import Literal

from app.domains.base_request import BaseRequest

from .labels import SimilarBooksNodeTypeEnum


class SimilarBooksSearch(BaseRequest):
    """Purpose: Find the books most similar in meaning to a book the user named.

    Args: none — this node reads nothing out of the goal description. What it
        searches for is built from the anchor books themselves.

    Returns: BookCandidateOutput — the books nearest the anchor, nearest first.
    A pool to choose from, not a final answer.

    depends_on: 1+ nodes returning BookAnchorOutput — Retrieve_by_Title, the
    node for a book the user named. A bibliography, a subject search or a
    numeric search returns BookCandidateOutput and CANNOT anchor this node:
    "mystery" matches hundreds of books, and averaging hundreds of blurbs
    describes nothing. A goal depending on one is skipped.

    Use when: the user names a book and wants more like it.
        - One book — "books like Dune": one Retrieve_by_Title, one goal here.
        - Several books BLENDED — "books like Dune and Neuromancer", "something
          between X and Y": ONE goal here, depending on every title retrieval.
          The anchors are folded into a single description, so the pool is what
          the named books have in common.
        - Several books SEPARATELY — "books like Dune or like Neuromancer",
          "recommendations for each of these": ONE GOAL PER BOOK, each depending
          on its own retrieval. Two goals, two pools. Pooling them into one goal
          would average two tastes into a description of neither.

    Do not use: when no book is named. Taste, mood and theme with nothing to
    anchor on ("something cozy and hopeful") are not this node's — it searches
    from the anchor books, not from the words in the goal. A subject word
    ("mysteries", "books about space") is Retrieve_by_Lexical_Traits.

    Constraints: every anchor a goal depends on is folded into one description
    and produces one pool — so AND is one goal with several depends_on, OR is
    several goals with one each. At most 5 anchor books in total across a
    goal's dependencies; more than that is refused rather than averaged.

    Example queries:
        - "recommend books like Dune"
        - "books like Dune and Neuromancer"        (one goal, two depends_on)
        - "books like Dune or like Neuromancer"    (two goals, one each)
    """

    node_type: Literal[SimilarBooksNodeTypeEnum.REQUEST] = (
        SimilarBooksNodeTypeEnum.REQUEST
    )
