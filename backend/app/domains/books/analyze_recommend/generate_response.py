"""Turn this node's finished work into the sentence the user actually reads.

The recommended books are already on screen as cards, so the reply is not a list
— it is the one thing the cards cannot say: why this set, given what was asked
for. So the model gets two summaries rather than two lists of books: the input
half (`summarize_references`) and the output half
(`RecommendationOutput.to_summary`).

Descriptions and isbn13s stay out — one would re-summarize a visible book, the
other is not prose.

Unlike the other LLM calls in this slice this is a plain streaming chat request,
not a tool call: the output *is* the reply, so `OpenAIChatRequest` carries the
SSE stream and the text reaches the client as it is written.
"""

from typing import Any, Iterable

from clients.messages import AssistantMessage
from app.common.prompt_loader import load_prompt
from app.common.sse_stream import SSEStream
from clients.openai_requests import OpenAIChatRequest

from app.domains.books.schemas import Book

from app.common.utils import count_values

RESPONSE_PROMPT_PATH = "domains/books/analyze_recommend/prompts/response_prompt.txt"

# ~150 words of reply is ~200 tokens; the rest is headroom for the model's
# reasoning tokens, which count against this budget on gpt-5 models.
MAX_RESPONSE_TOKENS = 600


def summarize_references(
    references: Iterable[Book],
    keywords: Iterable[str],
    bounds: str = "",
    found: int = 0,
) -> dict[str, Any]:
    """The input half: what the user pointed at, and what they asked for on top.

    Only `title`, `authors` and `genre` are read off each book, which keeps
    descriptions and identifiers out of the reply.

    `keywords` are the user's own words ("darker"), not the embedded anchor
    prose. That anchor is a 100-300 word book description; handing it to a
    model asked for a friendly reply gets it paraphrased back at the user.

    `bounds` is the measurable half of the ask ("under 300 pages"), which every
    book on screen already satisfies — those went into the search itself rather
    than being applied to its result. It is here so the reply can say so, since
    a constraint the user stated and the answer never acknowledges reads as a
    constraint ignored.

    `found` is how many candidates the search turned up in total. Paired with
    the recommendation count it is the difference between "here are ten" and
    "only these three exist" — and when it is 0 it is the whole story, which is
    a reply this node writes rather than an error it raises.

    Editions collapse to one entry per title before anything is counted —
    otherwise the title repeats ("books like Dune and Dune") and its author
    doubles, reading as a much stronger preference than was expressed.
    """
    by_title: dict[str, Book] = {}
    for book in references:
        by_title.setdefault(book.title, book)
    unique = list(by_title.values())

    return {
        "referenced_titles": [book.title for book in unique],
        "reference_authors": count_values(book.authors for book in unique),
        "reference_genres": count_values(book.genre for book in unique),
        "asked_for": ", ".join(keywords),
        "bounds": bounds,
        "candidates_found": found,
    }


def _render_counts(counts: dict[str, int]) -> str:
    """`A (2), B` — the count only where it exceeds one, since "(1)" after
    every name reads as data to report rather than context."""
    return ", ".join(
        name if n == 1 else f"{name} ({n})" for name, n in counts.items()
    )


def render_summaries(
    input_summary: dict[str, Any], output_summary: dict[str, Any]
) -> str:
    """The block the response prompt reads.

    Labelled lines rather than a dumped dict: the prompt asks for a reply that
    does not sound technical, and `{'genre_num': Counter(...)}` is a shape
    models happily imitate. Empty fields are dropped rather than printed as
    None, which reads as a value worth mentioning.
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

    bounds = input_summary.get("bounds")
    if bounds:
        # in `input` rather than `output` because it is what was *asked*: the
        # bounds went into the search itself, so every book below satisfies
        # them, and if none do that is what the counts say instead
        lines.append(f"- limited to: {bounds}")

    lines.append("")
    lines.append("output:")
    num_books = output_summary.get("num_books", 0)
    lines.append(f"- {num_books} books recommended")

    # How big the pool was, whenever it is not simply the answer. Both
    # directions matter to the reply: a pool of 3 means "these are all there
    # are" rather than a shortlist, and a pool of 12 that recommended 0 means
    # the search found books and the exclusions took them.
    #
    # Always stated when nothing was recommended, even at 0 — that is the one
    # case where the reply is *about* the pool, and an omitted line would leave
    # "found nothing" and "found some, kept none" indistinguishable.
    found = input_summary.get("candidates_found", 0)
    if found != num_books or not num_books:
        lines.append(f"- {found} came close enough to consider")

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
