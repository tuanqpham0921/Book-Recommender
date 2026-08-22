from app.domains.base_request import BaseRequest

from pydantic import BaseModel, Field
from typing import Literal

from db.schema import BookMetadataFilter
from .labels import FilterRetrievalNodeTypeEnum


class FilterRetrieval(BaseRequest):
    """Purpose: Narrow a prior retrieval's books by metadata — pages, year, rating, ratings count, child-friendly.

    Args:
        filters: The metadata bounds to apply. Every field is inclusive and
            independent — supply only the ones the user actually stated.

    Returns: BookRetrievalOutput — the subset that satisfies every bound.

    depends_on: exactly 1 node that produces books (BookRetrievalOutput, or
    either half of it — BookAnchorOutput, BookCandidateOutput) — this node
    narrows one result set rather than combining several, so pool with
    Combine_Union first if the bounds apply to more than one. Never
    Retrieve_Random: see Constraints.

    Use when: the request adds a measurable limit to a search that already has a
    subject — "by Sanderson, over 400 pages", "fantasy published after 2015",
    "highly rated with lots of reviews".

    Do not use: when the limits are all the request has. "Books under 200
    pages", "show me some well rated books" — there is nothing here to narrow,
    and a bound with no subject is Retrieve_by_Numeric_Traits, which searches the
    whole catalog by the same bounds. The split is only about whether the request
    has another subject in it: with one, the bounds come here; without one, they
    are the search. Do not use for genre, author, title or theme either —
    those are search subjects with their own retrieval nodes. And do not use to
    bound a similarity search: a filter node after the fact can only delete,
    which on a ranked pool throws the ranking away and often leaves nothing —
    the bounds have to go *inside* the vector search to narrow what it ranks.
    STALE (2026-08-22): Analyze_Similar_Books used to read those bounds out of
    its own goal text and do exactly that; it no longer parses anything, so a
    bound stated alongside "books like X" currently has nowhere to go and is
    dropped. Resolve when this node is unparked.

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


class FilterRetrievalArgs(BaseModel):
    """Narrow books an earlier step already found, to those inside the metadata
    bounds the query states."""

    filters: BookMetadataFilter = Field(
        ...,
        description="Metadata bounds to narrow the depended-on books by.",
    )
