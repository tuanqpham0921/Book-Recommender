"""Turn this node's finished work into the sentence the user actually reads.

By the time this runs the recommended books are already on screen as cards, so
the reply is not a list — it is the one thing the cards cannot say: why this
set, given what was asked for. That is a question about the *shape* of the
input and the output, so the model is handed two summaries rather than two
lists of books:

- the input half (`summarize_references`) — which titles were referenced, and
  what the user asked for on top of them.
- the output half (`RecommendationOutput.to_summary`) — how many books, whose,
  which genres, how long.

Descriptions and isbn13s stay out. A description would come back to the user
as a re-summary of a book they can already see, and an identifier is not prose.

Unlike every other LLM call in this slice this one is a plain streaming chat
request, not a tool call: the output *is* the reply, so `OpenAIChatRequest`
carries the SSE stream and the text reaches the client token by token as it is
written.
"""

from typing import Any, Iterable

from app.common.messages import AssistantMessage
from app.common.prompt_loader import load_prompt
from app.common.sse_stream import SSEStream
from clients.openai_requests import OpenAIChatRequest

from .schemas import ReferenceBook, count_values

RESPONSE_PROMPT_PATH = "domains/books/analyze_recommend/prompts/response_prompt.txt"

# ~150 words of reply is ~200 tokens; the rest is headroom for the model's
# reasoning tokens, which count against this budget on gpt-5 models.
MAX_RESPONSE_TOKENS = 600


def summarize_references(
    references: Iterable[ReferenceBook], semantic_input: str | None
) -> dict[str, Any]:
    """The input half: what the user pointed at, and what they asked for on top.

    `semantic_input` is the user's own phrase as the argument parser read it
    ("but darker"), *not* the anchor prose that was embedded. The anchor is a
    100-300 word book description written by the reference analyzer; handing
    that to a model asked for a friendly reply gets the description paraphrased
    back at the user, which is neither friendly nor an explanation.

    Editions are collapsed to one entry per title before anything is counted.
    The catalog holds several editions of a book and a title retrieval returns
    all of them, so counting rows would both repeat the title ("books like
    Dune and Dune") and double its author — "Jane Austen (2)" for a user who
    named one novel reads as a much stronger preference than they expressed.
    """
    by_title: dict[str, ReferenceBook] = {}
    for book in references:
        by_title.setdefault(book.title, book)
    unique = list(by_title.values())

    return {
        "referenced_titles": [book.title for book in unique],
        "reference_authors": count_values(book.authors for book in unique),
        "reference_genres": count_values(book.genre for book in unique),
        "asked_for": semantic_input,
    }


def _render_counts(counts: dict[str, int]) -> str:
    """`A (2), B` — the count only where it is more than one, because "(1)"
    after every name reads as data to be reported rather than context."""
    return ", ".join(
        name if n == 1 else f"{name} ({n})" for name, n in counts.items()
    )


def render_summaries(
    input_summary: dict[str, Any], output_summary: dict[str, Any]
) -> str:
    """The block the response prompt reads.

    Rendered as labelled lines rather than dumped as a dict: the prompt asks
    for a reply that does not sound technical, and `{'genre_num': Counter(...)}`
    is a shape models happily imitate. Empty fields are dropped instead of
    printed as None — an absent line is read as "not applicable", a `None` is
    read as a value worth mentioning.
    """
    lines: list[str] = ["input:"]

    titles = input_summary.get("referenced_titles") or []
    if titles:
        lines.append(f"- referenced books: {', '.join(titles)}")

    authors = input_summary.get("reference_authors") or {}
    if authors:
        lines.append(f"- by: {_render_counts(authors)}")

    genres = input_summary.get("reference_genres") or {}
    if genres:
        lines.append(f"- shelved as: {_render_counts(genres)}")

    asked_for = input_summary.get("asked_for")
    if asked_for:
        lines.append(f"- asked for: {asked_for}")

    lines.append("")
    lines.append("output:")
    lines.append(f"- {output_summary.get('num_books', 0)} books recommended")

    out_authors = output_summary.get("authors") or {}
    if out_authors:
        lines.append(f"- by: {_render_counts(out_authors)}")

    out_genres = output_summary.get("genres") or {}
    if out_genres:
        lines.append(f"- shelved as: {_render_counts(out_genres)}")

    min_pages, max_pages = output_summary.get("min_pages"), output_summary.get("max_pages")
    if min_pages and max_pages:
        lines.append(f"- length: {min_pages}-{max_pages} pages")

    return "\n".join(lines)


def build_response_request(
    summary_text: str, sse_stream: SSEStream
) -> OpenAIChatRequest:
    """Ask the LLM for the user-facing reply, streamed as it is written."""
    if not summary_text.strip():
        raise ValueError("No recommendation summary to write a response from")

    return OpenAIChatRequest(
        prompt=load_prompt(prompt_path=RESPONSE_PROMPT_PATH),
        model="gpt-5-mini",
        reasoning_effort="minimal",
        # the summaries are this node's own work, not something the user typed
        messages=[AssistantMessage(content=summary_text)],
        # what makes this call stream to the client rather than return a string
        sse_stream=sse_stream,
        max_complete_chat_tokens=MAX_RESPONSE_TOKENS,
    )
