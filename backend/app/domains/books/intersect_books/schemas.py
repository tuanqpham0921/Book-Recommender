from app.domains.base_request import BaseRequest

from typing import Literal

from .labels import CombineIntersectNodeTypeEnum


class CombineIntersect(BaseRequest):
    """Purpose: Keep only the books that satisfy every one of several earlier searches at once.

    Args: none — this node reads nothing out of the goal description. What it
        intersects is decided entirely by what it depends on.

    Returns: BookRetrievalOutput — the books present in every depended-on
    result.

    depends_on: 2+ nodes producing books — BookRetrievalOutput, or either half
    of it (BookAnchorOutput, BookCandidateOutput). Any retrieval node, and
    Analyze_Similar_Books. **How each set was found does not matter here**: a
    title, a bibliography, a subject search, a page-count bound and a similarity
    pool are all just sets of books by the time they reach this node.

    Use when: the request states two or more conditions that must hold on the
    SAME book. Give each condition its own retrieval goal, then one goal here
    depending on all of them:
        - "fantasy books over 400 pages" → Lexical_Traits + Numeric_Traits
        - "did Jane Austen write thrillers?" → Author + Lexical_Traits
        - "horror by Stephen King over 500 pages" → Lexical_Traits + Author +
          Numeric_Traits, and ONE goal here over all three
        - "books like Dune that are under 300 pages" → Title →
          Analyze_Similar_Books, plus Numeric_Traits, and one goal here over
          those two
    This node is REQUIRED whenever conditions must combine: two goals with no
    dependency between them are pooled (OR), so leaving it out answers with MORE
    books rather than fewer — the opposite of what was asked.

    Do not use: when the request has one condition — there is nothing to
    intersect, and this node searches for nothing itself. Nor when the
    conditions are alternatives rather than requirements: "romance by Nora
    Roberts and mystery by Agatha Christie" is two answers, not one
    intersection, so it is two retrieval goals and no node here.

    Constraints: at least 2 dependencies; a goal with fewer is skipped. This
    node can only shrink what earlier goals found, never grow it. An empty
    result is a real answer — no book satisfied every condition at once.

    Example queries:
        - "Find me fantasy books over 400 pages."
        - "Did Jane Austen write thrillers?"
        - "What horror books has Stephen King written that are over 500 pages?"
    """

    node_type: Literal[CombineIntersectNodeTypeEnum.REQUEST] = (
        CombineIntersectNodeTypeEnum.REQUEST
    )
