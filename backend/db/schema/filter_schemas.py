from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from config import BookConstraints
from enum import Enum

class GenreEnum(str, Enum):
    FICTION    = "fiction"
    NONFICTION = "non-fiction"


class AudienceEnum(str, Enum):
    """Who a book is for, as the catalog can actually answer it.

    Resolved against `books.genre`, whose four values encode audience and
    fiction-ness together ("Children's Fiction"), never against
    `books.is_children` — that column is NULL on all 5,197 rows and matches
    nothing. See the note on `BookMetadataFilter.is_children`.

    Db-owned rather than slice-owned, beside `GenreEnum`, because both are
    value vocabularies over a `books` column that `BookStore.lexical_query`
    switches on. That keeps every parameter in its signature a db type, so the
    store never has to import a node's args model.
    """

    CHILDREN = "children"
    ADULT = "adult"

class ExclusionBookFilter(BaseModel):
    """What a search rules OUT by name — never what it is about.

    Only what the user actually excluded: an author they did not mention is not
    an author they ruled out. Matching is by name rather than by id, so these
    are the words the ask used ("Herbert"), not catalog identifiers.
    """

    model_config = ConfigDict(extra="forbid")

    book_titles: Optional[list[str]] = Field(default=None, description="Titles to exclude.")
    authors: Optional[list[str]] = Field(default=None, description="Authors to exclude.")
    categories: Optional[list[str]] = Field(default=None, description="Categories or subgenres to exclude.")
    # keywords: Optional[list[str]] = Field(default=None, description="Keywords for semantic or fuzzy matching.")

    def model_post_init(self, __context) -> None:
        if self.book_titles:
            self.book_titles = list(set(self.book_titles))
        
        if self.authors:
            self.authors = list(set(self.authors))
        
        if self.categories:
            self.categories = list(set(self.categories))


# The min/max field pairs, as (low, high) — read by the inverted-range check
# below so it reads as the four ranges it guards rather than four if-statements.
_BOUNDED_RANGES = (
    ("min_pages", "max_pages"),
    ("min_rating", "max_rating"),
    ("min_ratings_count", "max_ratings_count"),
    ("min_year", "max_year"),
)


class BookMetadataFilter(BaseModel):
    """Book metadata expressed as measurable bounds.

    Ranges are inclusive on both ends, and each bound is independent — supply one,
    the other, or both.

    **The field descriptions carry the calibration for vague language**, and that
    is the reason they are so wordy. "Well rated", "popular", "a quick read",
    "the classical period" are all real asks that have to become a number
    somewhere, and this one model is shipped inside every tool schema that takes
    bounds — `FindByNumericTraitsArgs.traits` and `FilterRetrievalArgs.filters`.
    Written here, the mapping reaches both and they cannot disagree; written in
    either slice's docstring, it would be copied into the other and drift.

    Each description leads with the value to use and mentions the corpus range
    only where it stops a mistake. That order is load-bearing: an earlier draft
    opened with "Corpus range is 1876-2019" and `gpt-5-nano` answered "the
    classical period" with `max_year: 1876` — it took the nearest number in the
    sentence rather than the calibrated one.

    The thresholds are prompt text tuned against this corpus, not application
    limits — nothing in code reads them back, so they stay literal here rather
    than moving to `config/constants.py`. Only the corpus *ranges* come from
    `BookConstraints`. Retune them against the real distribution, not intuition:
    the counts quoted below are from the 5,197-book catalog as of 2026-08-20.

    Whether bounds may be the *subject* of a search or only a narrowing of one is
    a question about nodes, not about this model — see
    `FindByNumericTraitsRetrieval` (subject) and `FilterRetrieval` (narrowing).
    """

    model_config = ConfigDict(extra="forbid")

    min_pages: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            f"Minimum page count, inclusive. Corpus range is "
            f"{BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}, "
            f"median 312. Use 500 for 'long', 'epic' or 'a chunky read'."
        ),
    )
    max_pages: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            f"Maximum page count, inclusive. Corpus range is "
            f"{BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}, "
            f"median 312. Use 200 for 'short', 'a quick read' or 'a novella'."
        ),
    )

    # KNOWN DEAD: `books.is_children` is NULL on all 5,197 rows, so this bound
    # matches nothing and any goal that sets it answers zero books silently.
    # Audience is served by `AudienceEnum` on `FindByLexicalTraitsArgs`, which
    # resolves against `books.genre` (447 rows). Kept rather than removed by
    # owner decision; removing it means deleting the field and its two lines in
    # `metadata_predicates`.
    is_children: Optional[bool] = Field(
        default=None,
        description=(
            "True keeps only child-friendly books, False excludes them. Use True "
            "for 'for kids' or \"children's books\". Omit when the user did not say."
        ),
    )

    min_rating: Optional[float] = Field(
        default=None,
        ge=BookConstraints.MIN_RATING,
        le=BookConstraints.MAX_RATING,
        description=(
            f"Minimum average rating, inclusive, on a {BookConstraints.MIN_RATING}-"
            f"{BookConstraints.MAX_RATING} scale. Ratings cluster high — the corpus "
            f"median is 3.9 — so a low bound excludes almost nothing. Use 4.0 for "
            f"'well rated' or 'good ratings', and 4.3 for 'highly rated', "
            f"'the best' or 'highest rated'."
        ),
    )
    max_rating: Optional[float] = Field(
        default=None,
        ge=BookConstraints.MIN_RATING,
        le=BookConstraints.MAX_RATING,
        description=(
            f"Maximum average rating, inclusive, on a {BookConstraints.MIN_RATING}-"
            f"{BookConstraints.MAX_RATING} scale. Rarely what a user means: "
            f"'badly rated' is an ask, 'well rated' is not — that is min_rating."
        ),
    )

    min_ratings_count: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Minimum number of ratings, inclusive — how many people rated it, not "
            "how highly. Corpus median is about 1,100. Use 10000 for 'popular', "
            "'widely read', 'well-reviewed', 'most people love' or 'lots of reviews'."
        ),
    )
    max_ratings_count: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Maximum number of ratings, inclusive. Use 1000 for 'obscure', "
            "'underrated', 'a hidden gem' or 'nobody has heard of'."
        ),
    )

    min_year: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            f"Earliest publication year, inclusive. Use 2010 for 'recent', 'new' "
            f"or 'modern'. Nothing in the catalog was published after "
            f"{BookConstraints.MAX_PUBLISHED_YEAR}, so never use the current year."
        ),
    )
    max_year: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Latest publication year, inclusive. Use 1970 for 'classic', 'the "
            "classical period', 'old' or 'from an earlier era' — 1970 is the "
            "cutoff to use, not the oldest book in the catalog."
        ),
    )

    @model_validator(mode="after")
    def _reject_inverted_ranges(self) -> "BookMetadataFilter":
        """An inverted range is unanswerable, so it fails here rather than in SQL.

        `metadata_predicates` ANDs the two bounds independently, so min > max
        compiles to a WHERE that can never hold: zero rows, indistinguishable
        from an ordinary miss. Raising instead makes the runner skip the one goal
        and say which field pair was wrong.
        """
        for low_name, high_name in _BOUNDED_RANGES:
            low, high = getattr(self, low_name), getattr(self, high_name)
            if low is not None and high is not None and low > high:
                raise ValueError(
                    f"{low_name} ({low}) is above {high_name} ({high}) — no book "
                    "can satisfy both"
                )
        return self


class BooksFilter(BookMetadataFilter):
    # TODO: make sure the list are safe with max items
    authors: Optional[list[str]] = Field(default=None, description="Authors to include.")
    categories: Optional[list[str]] = Field(default=None, description="List of categories or subgenres.")
    keywords: Optional[list[str]] = Field(default=None, description="Keywords for semantic or fuzzy matching.")
    # fuzzy_priority: Optional[Literal["authors", "categories"]] = Field(default=None, description="Fuzzy match priority of genere or author")

    genre: Optional[GenreEnum] = Field(default=None, description="Main genre of the book.")
    # language: Optional[str] = Field(default=None, description="Language code (e.g., 'en').")
    # edition_type: Optional[str] = Field(default=None, description="Edition type (paperback, hardcover, ebook).")

    sort_by: Optional[Literal["rating", "page_count", "published_year"]] = None
    sort_order: Literal["asc", "desc"] = "desc"

    # limit: int = Field(default=BookConstraints.default_limit)
    exclusion: Optional[ExclusionBookFilter] = None

    def model_post_init(self, __context) -> None:
        super().model_post_init(__context)

        if self.authors:
            self.authors = list(set(self.authors))

        if self.categories:
            self.categories = list(set(self.categories))

        if self.keywords:
            self.keywords = list(set(self.keywords))

