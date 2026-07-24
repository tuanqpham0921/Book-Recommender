from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from config import BookConstraints
from enum import Enum

class GenreEnum(str, Enum):
    FICTION    = "fiction"
    NONFICTION = "non-fiction"

class ExclusionBookFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    book_titles: Optional[list[str]] = Field(default=None, description="Titles to exclude.")
    authors: Optional[list[str]] = Field(default=None, description="Authors to exclude.")
    categories: Optional[list[str]] = Field(default=None, description="List of categories or subgenres.")
    # keywords: Optional[list[str]] = Field(default=None, description="Keywords for semantic or fuzzy matching.")

    def model_post_init(self, __context) -> None:
        if self.book_titles:
            self.book_titles = list(set(self.book_titles))
        
        if self.authors:
            self.authors = list(set(self.authors))
        
        if self.categories:
            self.categories = list(set(self.categories))


class BookMetadataFilter(BaseModel):
    """Book metadata a search can be narrowed BY — never what a search is about.

    Every field here is a constraint: it can only shrink a result set that some
    anchor (title, author, genre, semantic description) already defined. A request
    made of these alone has no subject and should be sent back for clarification
    rather than given an invented anchor.

    Ranges are inclusive on both ends, and each bound is independent — supply one,
    the other, or both.
    """

    model_config = ConfigDict(extra="forbid")

    min_pages: Optional[int] = Field(
        default=None,
        description=f"Minimum page count, inclusive. Corpus range is {BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}.",
    )
    max_pages: Optional[int] = Field(
        default=None,
        description=f"Maximum page count, inclusive. Corpus range is {BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}.",
    )

    is_children: Optional[bool] = Field(
        default=None,
        description="True keeps only child-friendly books, False excludes them. Omit when the user did not say.",
    )

    min_rating: Optional[float] = Field(
        default=None,
        description=f"Minimum average rating, inclusive, on a {BookConstraints.MIN_RATING}-{BookConstraints.MAX_RATING} scale.",
    )
    max_rating: Optional[float] = Field(
        default=None,
        description=f"Maximum average rating, inclusive, on a {BookConstraints.MIN_RATING}-{BookConstraints.MAX_RATING} scale.",
    )

    min_ratings_count: Optional[int] = Field(
        default=None,
        description="Minimum number of ratings, inclusive — how many people rated it, not how highly. Use for 'popular' or 'well-reviewed'.",
    )
    max_ratings_count: Optional[int] = Field(
        default=None,
        description="Maximum number of ratings, inclusive. Use for 'obscure' or 'underrated'.",
    )

    min_year: Optional[int] = Field(
        default=None,
        description=f"Earliest publication year, inclusive. Corpus range is {BookConstraints.MIN_PUBLISHED_YEAR}-{BookConstraints.MAX_PUBLISHED_YEAR}.",
    )
    max_year: Optional[int] = Field(
        default=None,
        description=f"Latest publication year, inclusive. Corpus range is {BookConstraints.MIN_PUBLISHED_YEAR}-{BookConstraints.MAX_PUBLISHED_YEAR}.",
    )


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

    limit: int = Field(default=BookConstraints.default_limit)
    exclusion: Optional[ExclusionBookFilter] = None

    def model_post_init(self, __context) -> None:
        super().model_post_init(__context)

        if self.authors:
            self.authors = list(set(self.authors))

        if self.categories:
            self.categories = list(set(self.categories))

        if self.keywords:
            self.keywords = list(set(self.keywords))

