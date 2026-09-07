from typing import Literal

from app.domains.base_request import BaseRequest

from .labels import GenerateRecommendationsNodeTypeEnum


class RecommendationsGeneration(BaseRequest):
    """Purpose: Write the reply for a recommendation ask — show the books the
    earlier goals found and explain why they fit. The terminal step of every
    recommendation chain; it produces prose, not a book set.

    Args: none — what to write is the goal description; what to write *about*
        arrives from the goals this one depends on.

    Returns: RecommendationsOutput — the user-facing reply. Not a book set:
        no goal can retrieve from or compose on this one.

    depends_on: 1+ book-producing goals (BookAnchorOutput, BookCandidateOutput
    or BookRetrievalOutput) — typically the FINAL goal of the chain: the
    Analyze_Similar_Books pool, or the Combine_Intersect that narrowed it.
    Listing several goals means presenting all of them in one reply.

    Use when: the user wants book recommendations, whether or not they ask for
    an explanation. Every recommendation chain ends with exactly one goal of
    this type, depending on the chain's last book-producing goal.
        - "recommend books like Dune" — title retrieval → similarity search →
          one goal here depending on the similarity goal.
        - "books like Dune, and why?" — same plan; put the emphasis on
          explaining in this goal's description.

    Do not use: for lookups, counts or comparisons with no recommendation
    intent ("do you have Dune?", "how many mysteries do you have?"). Never in
    the middle of a chain — no goal may depend on this one.

    Constraints: one per recommendation chain, always last. Write the goal
    description as guidance for the reply — what was asked for, and what to
    explain about the picks.

    Example queries:
        - "recommend books like Dune"
        - "books like Dune and explain why each fits"
        - "recommend a long sci-fi novel"
    """

    node_type: Literal[GenerateRecommendationsNodeTypeEnum.REQUEST] = (
        GenerateRecommendationsNodeTypeEnum.REQUEST
    )
