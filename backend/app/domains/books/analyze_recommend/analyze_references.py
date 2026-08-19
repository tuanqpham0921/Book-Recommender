"""The reference-analysis call's pure half: documents in, request out.

Analyze_Recommend searches by vector, not keyword, so everything it depends on
has to collapse into one block of prose reading like the description of the
book the user wants next. `render_documents` builds the document block, and
`build_analysis_request` asks the LLM to fold it into `IdealBookDescription` —
the one string that gets embedded. The step that *runs* the request is
`RecommendBooksExecutor.analyze_references`, next door.

Two things stay out of the prompt. The reference books are excluded from the
search by isbn13 afterwards — a metadata filter, not something to ask prose to
enforce. And the isbn13s never reach the model: the prompt forbids identifiers
in the output, and in a description they only read as noise.
"""

from pydantic import BaseModel, Field

from clients.messages import AssistantMessage
from app.common.prompt_loader import load_prompt
from app.domains.books.schemas import Book
from clients import OpenAIParserRequest
from app.common.utils import truncate_str

ANALYZE_REFERENCES_PROMPT_PATH = (
    "domains/books/analyze_recommend/prompts/analyze_references.txt"
)

# The executor caps the anchor at a handful of books, so these bounds are a
# backstop against one pathological description rather than a real budget.
MAX_DOC_CHARS = 1500
MAX_TOTAL_CHARS = 8000


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


class IdealBookDescription(BaseModel):
    """The single description to embed, synthesized from the reference
    documents. Not a node request — it never reaches the planner, so it carries
    no node_type/confidence/reasoning. The class name is the tool name the
    model calls, so the prompt's Output section names it too."""

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
        tool_models=[IdealBookDescription],
        max_completion_tokens=2000,
    )
