from app.domains.base_request import BaseRequest

from pydantic import BaseModel, Field
from typing import Literal

from db.schema import BookMetadataFilter
from .labels import FindNumericTraitsNodeTypeEnum


class FindByNumericTraitsRetrieval(BaseRequest):
    """Purpose: Retrieve books by their measurable traits — rating, number of ratings, page count, publication year.

    Args:
        traits: The measurable bounds to search on. Every bound is inclusive and
            independent — supply only the ones the request actually states.

    Returns: BookCandidateOutput — the books inside those bounds.

    depends_on: None — this node queries the database directly.

    Use when: the request states any measurable bound — as figures or in words,
    both belong here: "under 200 pages", "published after 2015", "show me some
    well rated books", "what do you have from the classical period", "your most
    popular books", "something really long". The wording is turned into bounds
    by this node's own parse, so a goal description in the user's own words is
    enough.

    That includes a bound riding alongside another subject. Emit this node for
    the bound, a retrieval node for the subject, and ONE Combine_Intersect
    depending on both:
        - "fantasy books over 400 pages"
            → Retrieve_by_Lexical_Traits + this node + Combine_Intersect
        - "Stephen King books over 400 pages"
            → Retrieve_by_Author + this node + Combine_Intersect
    The intersect goal is not optional there: two goals with no dependency
    between them are pooled (OR), so emitting this node beside the subject one
    and stopping would answer with MORE books rather than fewer — the opposite
    of the bound.

    Do not use: for a superlative that asks for an ordering this node cannot
    give. "The single longest book" is not a bound; ask for "very long books"
    instead. Nor for a subject of any kind — a genre, theme, author or title is
    someone else's retrieval, and this node only ever contributes the numbers.

    Constraints: at least one bound — a request with nothing measurable in it is
    not this node, and an empty filter is refused. Bounds are combined as AND,
    and an inverted range ("over 400 pages, under 200 pages") is rejected rather
    than answered with nothing. This node searches on measurable traits alone
    and takes no title, author, genre or theme. Superlatives become bounds
    ("highest rated" → rated 4.3 or higher), so results are ordered by rating
    rather than by the trait that was asked about.

    Example queries:
        - "Find books with fewer than 200 pages."          (this node alone)
        - "Show me some well rated books."                 (this node alone)
        - "What books do you have from the classical period?"
        - "Find me obscure books nobody has heard of."
        - "Find me fantasy books over 400 pages."          (+ subject + intersect)
    """

    node_type: Literal[FindNumericTraitsNodeTypeEnum.REQUEST] = (
        FindNumericTraitsNodeTypeEnum.REQUEST
    )


class FindByNumericTraitsArgs(BaseModel):
    """Turn the query into measurable bounds, whether it states figures or words.

    Always fill in at least one bound: every query that reaches here has
    something measurable in it, and a vague word IS a bound — "obscure" and
    "really long" are as fillable as "under 200 pages". Returning nothing is the
    one wrong answer.

    Examples:
        "Find books with fewer than 200 pages."
            max_pages: 200
        "Show me some well rated books."
            min_rating: 4.0
        "Show me the highest rated books you have."
            min_rating: 4.3 — a superlative is the tighter bound, not an ordering
        "Find me obscure books nobody has heard of."
            max_ratings_count: 1000 — few people rated it, not badly rated
        "What books do you have from the classical period?"
            max_year: 1970
        "I want something really long."
            min_pages: 500
        "Your most popular books."
            min_ratings_count: 10000
        "Books between 300 and 500 pages published after 2015."
            min_pages: 300, max_pages: 500, min_year: 2015
    """

    # The per-field mapping lives on `BookMetadataFilter` rather than here. It
    # was shared with Filter_Retrieval's args until 2026-08-24, so that the two
    # could not calibrate "well rated" differently; that node is gone and this
    # is now the only shipper, but the split still earns its keep — the field
    # descriptions say what one bound means, and the examples above show
    # *combinations*, which no single field description can. This is the one
    # node whose whole job is the inference, so it is worth the tokens here.
    # Measured: without them, gpt-5-nano returned an empty filter for "obscure"
    # and "really long".
    #
    # `BookMetadataFilter` also carries `is_children`, a flag rather than a
    # measurement. Retrieve_by_Lexical_Traits now owns audience, and did *not* take
    # this field with it: it resolves audience against `books.genre`, while this
    # one still targets `books.is_children`, which is NULL on all 5,197 rows and
    # matches nothing. Setting it here is a silent zero — known and accepted;
    # see the note on `BookMetadataFilter.is_children`.
    traits: BookMetadataFilter = Field(
        ...,
        description="Measurable bounds to search the whole catalog by.",
    )
