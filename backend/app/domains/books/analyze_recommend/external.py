from pydantic import Field
from typing import Any
from app.domains.books.schemas import Book, BookRecommendationOutput
from app.common.utils import count_values

class RecommendationOutput(BookRecommendationOutput):
    """The books this node chose. An empty `books` means nothing in the
    catalog satisfied the anchor plus the filters.

    `references` and `search_text` are kept because this node's answer is not
    checkable without them: "why these books" is only answerable against what
    was pointed at and what was actually embedded. They also feed the response
    generator, which explains the set to the user (generate_response.py).

    Note `search_text` is not `args.semantic_input`. `args` stays exactly as
    the argument parser filled it — the user's own words, which the eval suite
    diffs — while `search_text` is the assembled anchor prose plus those words,
    which is what the embedding actually saw.
    """

    references: list[Book] = Field(default_factory=list)
    search_text: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the chosen set, not the books in it.

        Counts and ranges, deliberately: this feeds the response generator,
        which is asked to characterize the set ("various authors, shorter and
        longer reads") rather than list it. Titles here would only invite the
        model to enumerate what the book cards on screen already show.
        """
        pages = [book.num_pages for book in self.books if book.num_pages]
        return {
            "num_books": len(self.books),
            "authors": count_values(book.authors for book in self.books),
            "genres": count_values(book.genre for book in self.books),
            # None rather than 0 when the catalog has no page counts: a range
            # of 0-0 reads as "very short books" to whatever consumes this
            "min_pages": min(pages) if pages else None,
            "max_pages": max(pages) if pages else None,
        }