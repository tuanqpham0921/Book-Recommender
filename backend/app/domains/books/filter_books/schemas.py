from app.domains.base_request import BaseRequest

from pydantic import Field
from typing import Literal

from db.schema import BookMetadataFilter
from .labels import FilterRetrievalNodeTypeEnum


class FilterRetrieval(BaseRequest):
    """Purpose: Narrow a prior retrieval's books by metadata — pages, year, rating, ratings count, child-friendly.

    Args:
        filters: The metadata bounds to apply. Every field is inclusive and
            independent — supply only the ones the user actually stated.

    Returns: BookRetrievalOutput — the subset that satisfies every bound.

    depends_on: exactly 1 node that produces books (BookRetrievalOutput,
    BookRecommendationOutput) — this node narrows one result set rather than
    combining several, so pool with Combine_Union first if the bounds apply to
    more than one. Never Retrieve_Random: see Constraints.

    Use when: the request adds a measurable limit to a search that already has a
    subject — "by Sanderson, over 400 pages", "fantasy published after 2015",
    "highly rated with lots of reviews".

    Do not use: when the limits are all the request has. Page count, year and
    rating can narrow a search but cannot BE one, so a request made only of them
    has no subject and should be sent back for clarification rather than given
    an invented anchor. Do not use for genre, author, title or theme either —
    those are search subjects with their own retrieval nodes. And do not use to
    bound a recommendation: Analyze_Recommend reads the bounds out of its own
    goal text and runs this same narrowing over its candidate pool *before* it
    picks, so it answers with the closest books that already fit — leave the
    bounds in that goal's description. A filter node after the fact can only
    delete, which on a ranked recommendation throws the ranking away and often
    leaves nothing.

    Constraints: at least one filter bound — an empty filter is a no-op and
    will be refused. Bounds are combined as AND. This node searches for nothing
    of its own: it only narrows what the step it depends on already found, so it
    can shrink that set and never grow it. It may never depend on
    Retrieve_Random: that node returns one arbitrarily chosen book, so filtering
    it afterwards discards the pick and answers with nothing far more often than
    not. A bounded surprise ("surprise me with a short sci-fi") puts the bounds
    in Retrieve_Random's own filters, so the pick is drawn from inside them.

    Example queries:
        - "books by Brandon Sanderson over 400 pages"
        - "fantasy published after 2015"
        - "Agatha Christie, but only the well-reviewed ones"
    """

    node_type: Literal[FilterRetrievalNodeTypeEnum.REQUEST] = (
        FilterRetrievalNodeTypeEnum.REQUEST
    )


class FilterRetrievalArgs(FilterRetrieval):
    """The arguments this node parses out of its own goal text.

    See `FindByTitleArgs` — same split, same reason: the request above is what
    the planner reads and chooses by, this is what the node's own parse call
    fills in and ships as its tool schema.
    """

    filters: BookMetadataFilter = Field(
        ...,
        description="Metadata bounds to narrow the depended-on books by.",
    )
