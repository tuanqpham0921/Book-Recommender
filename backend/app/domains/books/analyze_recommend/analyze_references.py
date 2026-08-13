"""Fold this node's dependent results into one embedding-ready description.

Analyze_Recommend searches by vector, not keyword, so everything it depends on
has to collapse into one block of prose reading like the description of the book
the user wants next. Two steps:

1. `ParsedDependents` sorts the declared `anchors` by what is on each — rows, or
   the query that would fetch them. An anchor with neither lands in `unknown`
   rather than being dropped.
2. `render_documents` builds the document block, and `build_analysis_request`
   asks the LLM for the one string to embed.

Two things stay out of the prompt. The reference books are excluded from the
search by isbn13 afterwards — a metadata filter, not something to ask prose to
enforce. And the isbn13s never reach the model: the prompt forbids identifiers
in the output, and in a description they only read as noise.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from clients.messages import AssistantMessage
from app.common.prompt_loader import load_prompt
from app.domains.books.schemas import Book
from clients import OpenAIParserRequest
from db.stores import DeferredBookQuery
from app.common.utils import truncate_str

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
    """The node's anchors sorted by what it can do with each one.

    `RecommendInput.anchors` already selected them, so everything arriving here
    is a book-producing output. What is left is the real choice: rows if a
    dependency has them, otherwise the query that would produce them.

    `reports` is read by duck typing — `AnalyzeBooksOutput` is a reserved name
    with no class yet. This is the seam for the first node that produces one.
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
    # "<task id>: <class name>" for anything this node can't read — an anchor
    # that carries neither rows nor a query, i.e. a retrieval that matched
    # nothing. A real state to report, not a routing mistake.
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def from_anchors(cls, anchors: Sequence[Any]) -> "ParsedDependents":
        parsed = cls()
        for result in anchors:
            task_id = getattr(result, "id", None) or "?"
            claimed = False

            # Rows, or the query that would produce them — never both. A node
            # that fetched rows also carries the query it used, and counting
            # both would weight that set twice in the anchor.
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

def render_documents(books: list[Book], reports: list[str]) -> str:
    """The document block the analyzer prompt reads.

    Only `title` and `description` are read off each book, which keeps
    thumbnails, ratings and years out of a prompt asking for a description. The
    narrowing lives here rather than in a narrower book model.

    Grouped by title because the same title arriving twice is normal — the
    catalog holds several editions and a title retrieval returns all of them.
    Grouping shows the model that two descriptions are one book, not a doubled
    preference.
    """
    blocks: list[str] = []

    by_title: dict[str, list[str]] = {}
    for book in books:
        if not book.description:
            continue
        by_title.setdefault(book.title, []).append(
            truncate_str(book.description, MAX_DOC_CHARS)
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
        blocks.append(f"[report {i}]\n{truncate_str(report, MAX_DOC_CHARS)}")

    return truncate_str("\n\n".join(blocks), MAX_TOTAL_CHARS, collapse=False)

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
        # matches build_arg_parser_request in executor.py: the documents are
        # prior system work, not something the user typed
        messages=[AssistantMessage(content=document_text)],
        tool_models=[ReferenceAnalysis],
        max_completion_tokens=2000,
    )
