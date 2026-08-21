from typing import Literal

from pydantic import BaseModel, Field

from app.domains.base_request import BaseRequest
from db.schema import AudienceEnum, GenreEnum

from .labels import FindCategoryNodeTypeEnum


class FindByCategoryRetrieval(BaseRequest):
    """Purpose: Retrieve books by what they are ABOUT — subject, topic or shelf — optionally narrowed to fiction/non-fiction and to children or adults.

    Args:
        category: What to search the catalog's text for, and which shelves to
            keep. Subject keywords, fiction-ness and audience are ANDed together,
            so one node serves "non-fiction about artificial intelligence".

    Returns: BookRetrievalOutput — how many books match, and the query that
    reaches them.

    depends_on: None — this node queries the database directly.

    Use when: a subject word is the search. "fantasy books", "books about
    ninjas", "non-fiction about history", "children's books", "any good
    mysteries", "something set in space". This is a **lexical** search: it finds
    books whose title, shelf label or description actually contains these words.

    Do not use: for a known title (Retrieve_by_Title) or a named author
    (Retrieve_by_Author). And not for what a book is LIKE rather than what it is
    about — mood, tone and premise ("cozy", "hopeful", "slow-burn", "spooky")
    are Analyze_Recommend's semantic_input, which searches by meaning rather than
    by word. A request holding both splits across the two nodes: "cozy
    mysteries" is keywords=["mystery"] here plus semantic_input="cozy" there. A
    measurable bound riding alongside stays out of this node too — "fantasy books
    over 400 pages" is this node for the subject, then Filter_Retrieval for the
    page bound.

    Constraints: at least one of keywords, genre or audience — an empty search is
    refused rather than answered with the whole catalog. Keywords are ANDed, not
    ORed: every keyword must appear, so few high-signal words find more than many.
    Genre is exactly fiction or non-fiction, the only two the catalog
    distinguishes; every finer shelf word ("mystery", "history", "biography") is
    a keyword instead. One node covers one subject — two unrelated subjects
    ("mysteries and cookbooks") are two nodes.

    Example queries:
        - "Show me children's books."
        - "What non-fiction books about history do you have?"
        - "Find me books about artificial intelligence."
        - "Books about ninjas."
        - "Any good mysteries?"
    """

    node_type: Literal[FindCategoryNodeTypeEnum.REQUEST] = (
        FindCategoryNodeTypeEnum.REQUEST
    )


class FindByCategoryArgs(BaseModel):
    """Split one subject ask into words to search for and shelves to keep.

    Deliberately narrow, and deliberately not `BooksFilter` — that model already
    carries `keywords`, `categories` and `genre` and will look like the reusable
    option. It is the parked `Retrieve_Random` filter, and putting a `BooksFilter`
    on anything the planner reaches is what the V1 taxonomy decision removed.

    Examples:
        "Show me children's books."
            audience: children
        "Non-fiction about artificial intelligence."
            keywords: ["artificial intelligence"], genre: non-fiction
        "Any good mysteries?"
            keywords: ["mystery"] — "good" is a rating bound, not a subject, and
            belongs to another node
        "Books about ninjas."
            keywords: ["ninja"]
        "Children's books about space."
            keywords: ["space"], audience: children
    """

    keywords: list[str] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Subject words to find in the book's title, shelf label or "
            "description. Every keyword must appear, so fewer and more specific "
            "finds more: 'ninja' matches 1 book, 'space' 78, 'war' 442. Use the "
            "plain noun ('ninja', not 'ninja stories') — matching is by word "
            "stem, so plurals and tenses are handled for you. Leave empty when "
            "the request names no subject, only a shelf or an audience."
        ),
    )
    genre: GenreEnum | None = Field(
        default=None,
        description=(
            "Fiction or non-fiction — the only two the catalog distinguishes. "
            "Every finer shelf word ('mystery', 'history', 'romance', "
            "'biography') is a keyword instead, not a genre. Omit when the "
            "request did not say."
        ),
    )
    audience: AudienceEnum | None = Field(
        default=None,
        description=(
            "Who the book is for. Use 'children' for \"kids' books\", "
            "\"children's books\", 'for a 7 year old', 'young readers'. Use "
            "'adult' only when the request rules children out ('not a kids "
            "book'). Omit when it did not say."
        ),
    )
