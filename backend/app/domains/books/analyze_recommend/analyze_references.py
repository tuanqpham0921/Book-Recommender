"""Fold this node's dependent results into one embedding-ready description.

Analyze_Recommend doesn't search the catalog by keyword, it searches by vector
— so everything it depends on has to collapse into a single block of prose that
reads like the description of the book the user wants *next*. That happens in
two steps, kept apart on purpose:

1. `ParsedDependents` sorts the raw `dependent_results` dict by output shape.
   No LLM, no database — just "which of these can this node read". A shape it
   can't read lands in `unknown` instead of being silently dropped.
2. `render_documents` turns the materialized books and reports into the
   document block the LLM sees, and `build_analysis_request` asks it for the
   one string to embed (prompts/analyze_references.txt).

Two things deliberately stay out of the prompt. The reference books are
excluded from the search by isbn13 afterwards — "don't hand me back the book I
named" is a metadata filter, not something to ask prose to enforce. And the
isbn13s themselves never reach the model: they are identifiers, the prompt
forbids identifiers in the output, and glued into a description they only read
as noise.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.common.messages import AssistantMessage
from app.common.prompt_loader import load_prompt
from app.domains.books.schemas import Book
from clients import OpenAIParserRequest
from db.stores import DeferredBookQuery

ANALYZE_REFERENCES_PROMPT_PATH = (
    "domains/books/analyze_recommend/prompts/analyze_references.txt"
)

# The executor caps the anchor at a handful of books, so these bounds are a
# backstop against one pathological description rather than a real budget.
MAX_DOC_CHARS = 1500
MAX_TOTAL_CHARS = 8000

# NOTE:
# should this be a workflow or just as utils functions?
# workflow is nice because you have parsed_dependents as a step


@dataclass
class ParsedDependents:
    """`dependent_results` sorted by what this node can do with each entry.

    Keyed on the output *shape* (app/domains/books/schemas.py), read by duck
    typing rather than isinstance: `AnalyzeBooksOutput` is still a reserved
    name with no class behind it, so `reports` is the seam for the first node
    that produces one — nothing here has to change when it lands.
    """
    
    # TODO: have a rejected or .ok = False
    # this is for the dependents results
    # so you don't have to run this if all the dependents have no output
    # if there are stuff like recommend(brave new world, dune)
    # you can still generate, since I didn't find brave new world, I can only
    # here are some books similar to Dune...

    # what to fetch rows from — the anchor for the similarity search
    queries: list[DeferredBookQuery] = field(default_factory=list)
    # rows a dependency already chose (BookRecommendationOutput), used as-is
    books: list[Book] = field(default_factory=list)
    # written reports about books (AnalyzeBooksOutput, reserved)
    reports: list[str] = field(default_factory=list)
    # "<task id>: <class name>" for anything this node can't read
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def from_results(cls, dependent_results: dict[str, Any]) -> "ParsedDependents":
        parsed = cls()
        for task_id, result in dependent_results.items():
            claimed = False

            # Rows if the dependency has them, otherwise the query that would
            # produce them — never both. A node that fetched its own rows also
            # carries the query it fetched them with, and counting the set
            # twice would weight it twice in the anchor.
            books = getattr(result, "books", None)
            query = getattr(result, "query", None)
            if books:
                parsed.books.extend(books)
                claimed = True
            elif query is not None:
                parsed.queries.append(query)
                claimed = True

            report = getattr(result, "report", None)
            if report:
                parsed.reports.append(report)
                claimed = True

            if not claimed:
                parsed.unknown.append(f"{task_id}: {type(result).__name__}")

        return parsed

    def is_empty(self) -> bool:
        """No usable anchor. The node has nothing to be similar *to* and has to
        fall back on the user's own words."""
        return not (self.queries or self.books or self.reports)

    def to_summary(self) -> dict[str, Any]:
        return {
            "num_queries": len(self.queries),
            "num_books": len(self.books),
            "num_reports": len(self.reports),
            "unknown": self.unknown,
        }


def _truncate(text: str, limit: int, collapse: bool = True) -> str:
    """Cut at a word boundary so a clipped description doesn't end mid-word.

    `collapse` folds the internal whitespace of a single document onto one
    line; the assembled block passes False, because the blank lines between
    documents are what separate them.
    """
    text = " ".join(text.split()) if collapse else text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def render_documents(books: list[Book], reports: list[str]) -> str:
    """The document block the analyzer prompt reads.

    Only `title` and `description` are read off each book. That selection is
    what keeps thumbnails, ratings and years out of the prompt — the model is
    asked for a description, and metadata here is noise it tries to explain.
    The narrowing lives in this function on purpose; a narrower book model
    would only restate it one layer further away (app/domains/books/schemas.py).

    Books are grouped by title because the same title arriving twice is the
    normal case, not a duplicate: the catalog holds several editions of a book
    and a title retrieval returns all of them. Grouping shows the model that
    two descriptions describe one book, which is exactly what the prompt asks
    it to treat as extra context rather than as a doubled preference.
    """
    blocks: list[str] = []

    by_title: dict[str, list[str]] = {}
    for book in books:
        if not book.description:
            continue
        by_title.setdefault(book.title, []).append(
            _truncate(book.description, MAX_DOC_CHARS)
        )

    for i, (title, descriptions) in enumerate(by_title.items(), start=1):
        lines = [f"[reference {i}] {title}"]
        if len(descriptions) == 1:
            lines.append(descriptions[0])
        else:
            # numbered so the repetition reads as editions of one book
            lines.extend(
                f"edition {n}: {desc}" for n, desc in enumerate(descriptions, start=1)
            )
        blocks.append("\n".join(lines))

    for i, report in enumerate(reports, start=1):
        blocks.append(f"[report {i}]\n{_truncate(report, MAX_DOC_CHARS)}")

    return _truncate("\n\n".join(blocks), MAX_TOTAL_CHARS, collapse=False)

# TODO: rename this to ideal_book_description 
# or something similar
class ReferenceAnalysis(BaseModel):
    """The single description to embed, synthesized from the reference
    documents. Not a node request — it never reaches the planner, so it carries
    no node_type/confidence/reasoning."""

    semantic_input: str = Field(
        ...,
        description=(
            "A 100-300 word book description written only from the supplied "
            "documents: theme, plot shape, mood and setting. No titles, no "
            "author names, no identifiers, no metadata bounds."
        ),
        json_schema_extra={
            "example": (
                "A witty comedy of manners set among the landed gentry of a "
                "small rural community, where misjudgement and social pride "
                "keep two sharp-minded people apart…"
            )
        },
    )


def build_analysis_request(document_text: str) -> OpenAIParserRequest:
    """Ask the LLM to fold the document block into one embedding string."""
    if not document_text.strip():
        raise ValueError("No reference documents to analyze")

    return OpenAIParserRequest(
        prompt=load_prompt(prompt_path=ANALYZE_REFERENCES_PROMPT_PATH),
        model="gpt-5-mini",
        reasoning_effort="low",
        # matches build_arg_parser_request: the documents are prior system
        # work, not something the user typed
        messages=[AssistantMessage(content=document_text)],
        tool_models=[ReferenceAnalysis],
        max_completion_tokens=2000,
    )
