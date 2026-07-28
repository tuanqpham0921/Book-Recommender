"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import BaseRequest
from app.domains.books.node_types import BookNodeTypeEnum
from db.schema import BookMetadataFilter, BooksFilter
import logging

logger = logging.getLogger(__name__)


class CompareStrategy(BaseRequest):
    """Purpose: Contrast two or more named books — the analyze step when the user asks how titles differ or relate.

    Args:
        comparison_criteria: The user's comparison lens (theme, tone, length,
            style, etc.) when stated; omit when they only want a general comparison.

    Returns: Markdown-formatted comparison text, used directly as the assistant's reply.

    Use when: the user wants a side-by-side read on specific named books.

    Do not use: when they want new suggestions instead, or only want to find
    a single title.

    Constraints: needs two or more books retrieved first — a comparison of
    fewer is meaningless. Three or more titles → one retrieval per book.

    Example queries:
        - "Compare X and Y"
        - "how are X and Y different"
        - "compare their themes"
        - "which is longer / darker / more literary"
    """

    node_type: Literal[BookNodeTypeEnum.COMPARE] = BookNodeTypeEnum.COMPARE
    comparison_criteria: Optional[str] = Field(
        None, json_schema_extra={"example": "tone"}
    )

class RecommendationStrategy(BaseRequest):
    """Purpose: Suggest books that fit the user's ask — the analyze step for most recommendation queries.

    Args:
        semantic_input: What the books should be LIKE — theme, tone, mood or
            premise. Never a title, author, or shelf label; shelf words go to
            Retrieve_by_Genre.
        filters: Optional BooksFilter — pages, year, rating, ratings count,
            child-friendly — that the SEARCH ITSELF must respect. These are not
            applied to the depended-on books; they bound which candidates the
            similarity search is allowed to return.
    
    if no semantic_input or filters are provided, this node will find the closest books
    similar to the referenced book.

    Returns: Markdown-formatted recommendation text, used directly as the assistant's reply.

    Use when: the user wants new titles to read.
        - Similarity: "books like X", "more like X or Y" → retrieve X (and Y)
          first
        - Thematic / mood: "something cozy and hopeful" → semantic_input. A
          shelf word riding along ("cozy mysteries") splits: "mystery" to
          Retrieve_by_Genre, "cozy" stays here
        - Mixed: named anchor book(s) plus a twist ("like X but darker") →
          a supporting retrieval plus semantic_input
        - Any of the above with a measurable limit ("like X but under 300
          pages", "cozy mysteries rated 4+") → add filters

    Do not use: when they only want to look up a known book or an author's/genre's
    full catalog instead of suggestions.

    Constraints: needs a supporting retrieval step, so a retrieval is still
    required even for purely thematic requests with no named book.

    How this node's filters differ from Filter_Retrieval: this node SEARCHES
    within the bounds; Filter_Retrieval DELETES from a finished result. The
    bounds here go into the similarity query, so what comes back is the closest
    books that already satisfy them — including books no prior step retrieved.
    Filter_Retrieval can only remove books from a set that already exists and can
    never surface a new one. So "something like Dune, 100-200 pages" belongs
    here, in filters: putting it in a Filter_Retrieval afterwards would rank the
    nearest books to Dune first — mostly long ones — and then throw nearly all of
    them away, answering with a few poor matches or nothing at all. Narrow a
    plain retrieval with Filter_Retrieval; narrow a recommendation with filters.

    Example semantic_input: cozy and hopeful, slow-burn dread, epic with
    strong world-building, darker than the anchor book, a heist on a
    generation ship, quiet and character-driven, morally grey protagonist.
    """

    node_type: Literal[BookNodeTypeEnum.RECOMMENDATION] = BookNodeTypeEnum.RECOMMENDATION
    semantic_input: Optional[str] = Field(
        None, json_schema_extra={"example": "cozy and hopeful"}
    )
    filters: Optional[BooksFilter] = Field(
        default=None,
        description=(
            "Metadata bounds the similarity search must satisfy — applied inside "
            "the search, not to the depended-on books. Omit unless the user "
            "stated a measurable limit."
        ),
    )


class FindByTitleRetrieval(BaseRequest):
    """Purpose: Retrieve a single known book by its title from the database.

    Args:
        title: Book title to search for.

    Returns: A FindByTitleOutput — the searched title plus a list of matching
    BookSummary records (isbn13, title, authors, categories, genre,
    published_year, num_pages, average_rating, ratings_count, is_children).

    Use when: a specific title is named — "find Dune", "do you have The Great
    Gatsby".

    Do not use: when the author is the actual subject of the search ("books by
    Frank Herbert"), or when no specific title is named.

    Constraints: one title per node — for multiple named titles, emit one node
    per title. This node searches on the title alone and takes no author
    argument. When a title and an author are named together ("Dune by Frank
    Herbert"), or the question is whether a given author wrote a given title
    ("did Frank Herbert write Dune"), the author is a second retrieval
    dimension: emit Retrieve_by_Author alongside this node and AND them with
    Combine_Intersect. That checks the pairing against the data instead of
    taking it on trust, and an empty intersection is the real answer to "did X
    write Y?".

    Example queries:
        - "find Dune"
        - "do you have The Great Gatsby"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_TITLE] = BookNodeTypeEnum.FIND_TITLE
    title: str = Field(..., json_schema_extra={"example": "Dune"})


class FindByISBN13Retrieval(BaseRequest):
    """Purpose: Retrieve a single book by its exact ISBN13 from the database.

    Args:
        isbn13: ISBN13 to search for.

    Returns: A FindByISBN13Output — the searched isbn13 plus the matching
    BookSummary, or null if not found.

    Use when: an ISBN13 is explicitly given by the user, or already known from
    a prior step's result.

    Do not use: when only a title, author, or genre is known — the ISBN13 must
    be a literal identifier already in hand.

    Constraints: exactly one ISBN13 per node.

    Example queries:
        - "look up ISBN 9780441172719"
        - "what book is 978-0-14-303943-3"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_ISBN13] = BookNodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., json_schema_extra={"example": "9780441172719"})


class FindByAuthorRetrieval(BaseRequest):
    """Purpose: Retrieve the books written by one named author.

    Args:
        author: The single author whose books to retrieve.

    Returns: A FindByAuthorOutput — the searched author plus a list of matching
    BookSummary records.

    Use when: one author is the subject of the search.

    Do not use: for taste-based suggestions. For books two or more authors
    wrote *together*, use Retrieve_by_CoAuthors instead. When a title and an
    author are named together ("Dune by Frank Herbert", "did Frank Herbert
    write Dune"), this node is right but not on its own — Retrieve_by_Title
    carries the title, this node carries the author, and Combine_Intersect
    ANDs them.

    Constraints: exactly one author per node — several authors
    mean one node per author ("books by Austen and by Coelho"
    → two nodes), because each node returns one author's catalog.

    Example queries:
        - "books by Ursula K. Le Guin"
        - "what else has Brandon Sanderson written"
        - "show me some Agatha Christie"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_AUTHOR] = BookNodeTypeEnum.FIND_AUTHOR
    author: str = Field(..., json_schema_extra={"example": "Ursula K. Le Guin"})


class FindByCoAuthorsRetrieval(BaseRequest):
    """Purpose: Retrieve books that two or more named authors wrote together — their collaborations.

    Args:
        authors: The authors who must all appear on the same book (at least two).

    Returns: A FindByCoAuthorsOutput — the searched authors plus a list of
    matching BookSummary records, each credited to all of them.

    Use when: the query is about a collaboration — the named authors as
    co-writers of the same title, signalled by words like "together", "with",
    "co-wrote", "collaborated on", "as a duo".

    Do not use: when the authors are named as separate bibliographies to fetch
    side by side ("books by Austen and books by Coelho") — that is one
    Retrieve_by_Author per author. A single author alone is always
    Retrieve_by_Author, never this node.

    Constraints: at least two authors, and they are combined as AND, not OR —
    a book is only returned when every named author is credited on it, so this
    returns nothing when they never actually collaborated (which is itself the
    answer to "did they write anything together?").

    Example queries:
        - "what did Brian Herbert and Kevin J. Anderson write together"
        - "books co-written by Neil Gaiman and Terry Pratchett"
        - "did Charles Osborne and Agatha Christie collaborate on anything"
        - "show me the Preston and Child novels"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_COAUTHORS] = (
        BookNodeTypeEnum.FIND_COAUTHORS
    )
    authors: List[str] = Field(
        ...,
        min_length=2,
        json_schema_extra={"example": ["Brian Herbert", "Kevin J. Anderson"]},
    )


class FindByGenreRetrieval(BaseRequest):
    """Purpose: Retrieve books belonging to a named genre or category from the database.

    Args:
        genre: One shelf label — what a book is FILED UNDER, not what it is
            LIKE. Mood and premise ("cozy", "slow-burn") are
            Analyze_Recommend's semantic_input; a query holding both splits
            across the two nodes — "cozy mysteries" is genre="mystery" here
            plus semantic_input="cozy".

    Returns: A FindByGenreOutput — the searched genre plus a list of matching
    BookSummary records.

    Use when: genre is the primary axis of the search — "fantasy books", "any
    good mysteries", "nonfiction about space".

    Do not use: for a single known title, or when no word in the query names a
    shelf.

    Constraints: single genre per node — no cross-column filtering (e.g. genre
    plus a rating threshold isn't supported in this node). Several genres mean
    one node per genre.

    Example genres: fiction, non-fiction, children's fiction, children's
    non-fiction, mystery, thriller, horror, science fiction, fantasy, romance,
    poetry, drama, history, biography, philosophy, religion, science, comics &
    graphic novels, literary criticism.
    """

    node_type: Literal[BookNodeTypeEnum.FIND_GENRE] = BookNodeTypeEnum.FIND_GENRE
    genre: str = Field(..., json_schema_extra={"example": "fantasy"})


class RandomBookRetrieval(BaseRequest):
    """Purpose: Retrieve random books from the catalog — a surprise with no taste signal.

    Args:
        filters: Optional bounds the random pick must stay inside. Supply only
            what the user actually stated; a bare surprise takes no filters.
        limit: Optinal number of random books, default to 1

    Returns: A RandomBookOutput — one randomly selected BookSummary from within
    the given bounds.

    Use when: the user cedes the choice instead of describing what they want —
    examples "surprise me", "pick anything", "recommend me a book", "find 3 books" with nothing else
    said. A bare recommend like that is this node ALONE: it is a complete plan
    on its own, so do not add Analyze_Recommend after it. There is no taste
    input for a recommendation to work from, and this node already returns a
    book.

    Do not use: the moment the ask carries any taste, mood or anchor
    ("something spooky", "a book like Dune", "a good fantasy") — that is a real
    recommendation and belongs to Analyze_Recommend over a retrieval, because a
    random pick would ignore what they told you.

    Constraints: returns books, chosen arbitrarily. It queries the database
    directly and takes no depends_on. Because the pick is arbitrary, nothing
    downstream should narrow them — a filter applied afterwards usually discards
    the one book and answers with nothing; bounds belong in filters here, where
    the pick is drawn from inside them.

    Example queries:
        - "surprise me"
        - "pick anything"
        - "recommend me a book"
        - "surprise me with a short sci-fi"
    """

    node_type: Literal[BookNodeTypeEnum.RANDOM] = BookNodeTypeEnum.RANDOM
    filters: Optional[BooksFilter] = Field(
        default=None,
        json_schema_extra={
            "example": {"categories": ["Science Fiction"], "max_pages": 250}
        },
    )
    # NOTE: this can be post validated
    limit: int = Field(default=1, description="number of random books requested")


class UnionRetrieval(BaseRequest):
    """Purpose: Pool two or more prior retrieval results into one combined set — OR, not AND.

    Returns: A UnionRetrievalOutput — one deduplicated list of BookSummary
    records containing every book found by any of the depended-on steps.

    Use when: separate result sets have to become one explicit list before the
    next step can work on them — a later analyze step that reasons over all of
    them at once, or a single ranked/sorted answer drawn from several sources.

    Do not use: merely because the query names two things. Two bibliographies
    presented side by side need two retrieval nodes and nothing else; the next
    step reading both retrievals already pools them (OR) without a node. Reach
    for this node only when the pooled set is itself a step something downstream
    consumes. Never use to intersect — books matching ALL the inputs is
    Combine_Intersect.

    Constraints: at least two prior retrieval steps, combined as OR — a book is
    kept when any input found it. Duplicates across inputs collapse to one
    record. This node does nothing but pool: it carries no filters of its own,
    so narrowing the pooled set by page count, year or rating is a separate
    Filter_Retrieval step after this one. It reads prior results only and never
    queries the database, so it cannot widen what the retrievals already
    returned.

    Example queries:
        - "recommend something based on Austen's and Coelho's books"
        - "the longest book by either Sanderson or Jordan"
        - "put everything by these two authors in one list"
    """

    node_type: Literal[BookNodeTypeEnum.UNION_RETRIEVAL] = (
        BookNodeTypeEnum.UNION_RETRIEVAL
    )


class IntersectRetrievals(BaseRequest):
    """Purpose: Keep only the books found by ALL of two or more prior retrievals — AND, not OR.

    Returns: An IntersectRetrievalsOutput — one list of BookSummary records,
    each of which appeared in every depended-on step's result.

    Use when: the request names two or more search dimensions that must hold on
    the same book, and each dimension has its own retrieval node — most often
    an author plus a genre ("fantasy books by Sanderson" → Retrieve_by_Author
    plus Retrieve_by_Genre, intersected here). A title plus an author is the
    same shape ("Dune by Frank Herbert", "did Frank Herbert write Dune" →
    Retrieve_by_Title plus Retrieve_by_Author, intersected here) — the title
    node has no author argument, so this is the only place that pairing is
    checked. This node is the only way a plan says AND: prior steps read
    together are pooled (OR), so leaving this node out of a both-must-hold
    request quietly answers a different question.

    Do not use: when the inputs are alternatives rather than joint requirements.
    Two authors' books gathered into one answer, or one ranked list drawn from
    several searches, is a pool — have the next step read both retrievals
    directly and add no node here. Also do not use when the second dimension is a
    metadata constraint rather than a search subject: page count, year, rating,
    ratings count and child-friendly can only narrow, so they belong in a
    Filter_Retrieval, never in a retrieval node that then gets intersected. And
    not for books two authors wrote together — that is Retrieve_by_CoAuthors,
    which does the AND inside one query.

    Constraints: at least two prior retrieval steps, combined as AND — a book
    is kept only when every input found it, so an empty result is a real answer
    and not an error. This node does nothing but intersect: it carries no
    filters of its own, so narrowing the result by page count, year or rating is
    a separate Filter_Retrieval step after this one. It reads prior results only
    and never queries the database.

    Example queries:
        - "fantasy books by Brandon Sanderson"
        - "what children's books has Neil Gaiman written"
        - "mysteries by Agatha Christie"
    """

    node_type: Literal[BookNodeTypeEnum.INTERSECT_RETRIEVALS] = (
        BookNodeTypeEnum.INTERSECT_RETRIEVALS
    )


class FilterRetrieval(BaseRequest):
    """Purpose: Narrow a prior retrieval's books by metadata — pages, year, rating, ratings count, child-friendly.

    Args:
        filters: The metadata bounds to apply. Every field is inclusive and
            independent — supply only the ones the user actually stated.

    Returns: A FilterRetrievalOutput — the subset of the depended-on books that
    satisfy every supplied bound.

    Use when: the request adds a measurable limit to a search that already has a
    subject — "by Sanderson, over 400 pages", "fantasy published after 2015",
    "highly rated with lots of reviews".

    Do not use: when the limits are all the request has. Page count, year and
    rating can narrow a search but cannot BE one, so a request made only of them
    has no subject and should be sent back for clarification rather than given
    an invented anchor. Do not use for genre, author, title or theme either —
    those are search subjects with their own retrieval nodes. And do not use to
    bound a recommendation: Analyze_Recommend carries its own filters, which the
    similarity search applies while ranking, so it returns the closest books that
    already fit. This node runs after the fact and can only delete, which on a
    recommendation throws away the ranking and often leaves nothing.

    Constraints: at least one filter bound — an empty filter is a no-op and
    will be refused. Bounds are combined as AND. This node reads prior results
    only; it never queries the database, so it can only shrink what the prior
    steps already returned. It may never depend on Retrieve_Random: that node
    returns one arbitrarily chosen book, so filtering it afterwards discards
    the pick and answers with nothing far more often than not. A bounded
    surprise ("surprise me with a short sci-fi") puts the bounds in
    Retrieve_Random's own filters, so the pick is drawn from inside them.

    Example queries:
        - "books by Brandon Sanderson over 400 pages"
        - "fantasy published after 2015"
        - "Agatha Christie, but only the well-reviewed ones"
    """

    node_type: Literal[BookNodeTypeEnum.FILTER_RETRIEVAL] = (
        BookNodeTypeEnum.FILTER_RETRIEVAL
    )
    filters: BookMetadataFilter = Field(
        ...,
        description="Metadata bounds to narrow the depended-on books by.",
    )
