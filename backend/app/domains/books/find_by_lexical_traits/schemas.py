from typing import Literal

from pydantic import BaseModel, Field

from app.domains.base_request import BaseRequest
from db.schema import AudienceEnum, GenreEnum

from .labels import FindLexicalTraitsNodeTypeEnum


class FindByLexicalTraitsRetrieval(BaseRequest):
    """Purpose: Retrieve books by their lexical traits alone — the words the catalog's text actually contains, plus the shelves it files them under.

    Args:
        traits: The words to search the catalog's text for, and which shelves to
            keep. Keywords, fiction-ness and audience are ANDed together, so one
            node serves "non-fiction about artificial intelligence".

    Returns: BookCandidateOutput — how many books match, and the query that
    reaches them.

    depends_on: None — this node queries the database directly.

    Use when: a word IS the search. "fantasy books", "books about ninjas",
    "non-fiction about history", "children's books", "any good mysteries",
    "something set in space". This is a **lexical** search: it matches books
    whose title, shelf label or description literally contains these words. It is
    the node for anything that is neither a number nor an identifier — the
    counterpart of Retrieve_by_Numeric_Traits, which owns the measurable half of
    the same job.

    Do not use: for a known title (Retrieve_by_Title) or a named author
    (Retrieve_by_Author). Mood, tone and premise ("cozy", "hopeful",
    "slow-burn", "spooky") are not lexical traits — they describe what a book is
    *like*, and this node can only find words the catalog's text contains, so
    searching for a feel finds nothing. Keep the part of the request that is a
    real word in the text and leave the rest out: "cozy mysteries" is
    keywords=["mystery"]. A measurable bound riding alongside is likewise not
    this node's to apply — "fantasy books over 400 pages" searches the words here
    and leaves the page bound in the goal's description.

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

    node_type: Literal[FindLexicalTraitsNodeTypeEnum.REQUEST] = (
        FindLexicalTraitsNodeTypeEnum.REQUEST
    )


class FindByLexicalTraitsArgs(BaseModel):
    """Split one lexical ask into words to search for and shelves to keep.

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
            nothing here can apply it
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
