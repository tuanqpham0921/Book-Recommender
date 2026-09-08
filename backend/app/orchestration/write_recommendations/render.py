"""The writing call's pure half: sources and failures in, a request out.

`render_report` turns what the plan produced into the one block of text the
writer reads, and `build_recommendations_request` wraps it. Nothing here runs —
the step that executes the request is
`GenerateRecommendationsExecutor.write_recommendations`, next door.

The rendering is where the writer's whole world is decided, so two things stay
out of it. **Identifiers**: an isbn13 is not something to say in a sentence, and
a model that sees one will eventually print it. **Internal vocabulary**: the
entries are numbered and labelled by their goal instruction, never as "goals",
"nodes" or "queries" — the prompt forbids that language and the input should not
supply it either.

The report is evidence and nothing else. It used to open with a `What to write:`
brief — this stage's own goal instruction, the one line in the block the model
was told to obey — and that line went away with the goal (2026-09-08): an
unregistered stage has no planner text, so the *user's* message is the brief and
it travels as the `UserMessage` in `build_recommendations_request`. That makes
the trust split cleaner than it was, since the report no longer mixes a
direction in with the data.

One typed read reaches into a sibling slice: a source that is a
`SimilarBooksOutput` carries the anchor books it was built from and the
description it embedded, which are the actual "why these fit" material.
Interpretation of upstream shapes is the consuming stage's own job (rule 4 in
domains/README.md), and widening `BookCandidateOutput` so this stays
import-free would put two fields on a shared shape for one reader.
"""

from app.common.prompt_loader import load_prompt
from app.common.sse_stream import SSEStream
from app.common.utils import truncate_str
from app.domains.base_workflow import FailedGoalOutput
from app.domains.books.external import BookRetrievalOutput
from app.domains.books.find_similar_books import SimilarBooksOutput
from app.domains.books.schemas import Book
from clients import OpenAIChatRequest
from clients.messages import AssistantMessage, UserMessage

PROMPT_PATH = "orchestration/write_recommendations/prompts/write_recommendations.txt"

# A blurb is context for one sentence about a book, not the book's whole entry.
MAX_DESCRIPTION_CHARS = 400
MAX_TOTAL_CHARS = 12000

# What an entry with no goal instruction is headed by — an output that never
# travelled through the runner, which no registered plan produces today.
FALLBACK_HEADER = "part of the search"

# what the evidence is headed by
FINDINGS_HEADER = "What I found:"


def render_book(book: Book) -> str:
    """One book as the writer sees it.

    Fields picked by hand, which is what `Book`'s docstring asks for instead of
    a narrower model. No isbn13 and no thumbnail: the first is an identifier the
    prose must never contain, the second already travelled to the browser on the
    card.
    """
    facts = [book.authors or "author unknown"]
    if book.published_year:
        facts.append(str(book.published_year))
    if book.num_pages:
        facts.append(f"{book.num_pages} pages")
    if book.average_rating:
        facts.append(f"rated {book.average_rating}")

    line = f"- {book.title} — {', '.join(facts)}"
    if book.description:
        blurb = truncate_str(book.description, MAX_DESCRIPTION_CHARS)
        line += f"\n  {blurb}"
    return line


def render_source(index: int, source: BookRetrievalOutput, books: list[Book]) -> str:
    """One book-producing entry: what was asked, what came of it, the books.

    "found nothing" is rendered as its own sentence rather than a missing
    field, because it is an answer the reply has to relay — and a blank space
    relays it to nobody.

    The similarity pool gets two extra lines. Its books match a description the
    *system* wrote from the books the user named, and a reply explaining "why
    these fit" is only honest against that: what it was built from, and what
    was actually searched for.
    """
    header = f"[{index}] {source.goal_instruction or FALLBACK_HEADER}"

    lines = [header]
    if isinstance(source, SimilarBooksOutput):
        if source.references:
            named = ", ".join(book.title for book in source.references)
            lines.append(f"built from the reader's reference books: {named}")
        if source.search_text:
            lines.append(f'searched for books matching: "{source.search_text}"')

    if not source.num_books:
        lines.append("found nothing")
        return "\n".join(lines)

    lines.append(f"found {source.num_books} book(s)")
    if books:
        lines.append("\n".join(render_book(book) for book in books))
    return "\n".join(lines)


def render_failure(index: int, failure: FailedGoalOutput) -> str:
    """One entry that never produced books: what was asked, and why it stopped.

    `reason` arrives already composed for prose — the runner writes it plain
    and appends the upstream cause ("it needed X, which found nothing") —
    which is why this renders it verbatim instead of interpreting anything.
    """
    header = f"[{index}] {failure.goal_instruction or FALLBACK_HEADER}"
    line = "could not be completed"
    if failure.reason:
        line += f" — {failure.reason}"
    return f"{header}\n{line}"


def render_report(
    sources: list[BookRetrievalOutput],
    rows: list[list[Book]],
    failures: list[FailedGoalOutput],
) -> str:
    """Everything the plan produced as one block: the sources in the order the
    runner ran them, then what could not be done.

    Every entry is evidence — there is no longer a brief at the top, so nothing
    in this block is an instruction and the prompt can say so without an
    exception (see the module docstring).

    `rows` is positional against `sources` — the executor fetched them, and
    only it knows which sources it could afford to materialize, so an entry
    with an empty list here may still have matched books. That is why the count
    is rendered separately from the rows rather than inferred from them.
    """
    blocks = [FINDINGS_HEADER]
    blocks += [
        render_source(i, source, books)
        for i, (source, books) in enumerate(zip(sources, rows), start=1)
    ]
    blocks += [
        render_failure(i, failure)
        for i, failure in enumerate(failures, start=len(sources) + 1)
    ]
    return truncate_str("\n\n".join(blocks), MAX_TOTAL_CHARS, collapse=False)


def build_recommendations_request(
    rendered: str, sse_stream: SSEStream, user_message: str
) -> OpenAIChatRequest:
    """Ask the LLM to write the reply, streaming as it goes.

    `sse_stream` is required by `OpenAIChatRequest` and is the whole delivery
    mechanism: `OpenAIClient._chat_stream` pushes each `content.delta` to it, so
    the reply reaches the browser as it is written and the assembled text still
    comes back for the record.

    Two messages, and the split is the trust boundary. The rendered report is an
    `AssistantMessage` because it is prior system work — matching what
    `find_similar_books` does with its documents — and the prompt tells the
    model to read it as data, all of it, with no line exempted. The user's own
    text is the `UserMessage`: it is both the question being answered and, since
    this stage was deregistered and has no planner brief, the only direction the
    call carries. It goes last so the model is replying to it rather than
    continuing its own turn.

    A cheap model on purpose: this call writes prose from facts it was handed,
    which is not the job accuracy was bought for on the planner.
    """
    if not rendered.strip():
        raise ValueError("Nothing to write recommendations from")

    return OpenAIChatRequest(
        prompt=load_prompt(prompt_path=PROMPT_PATH),
        model="gpt-5-mini",
        reasoning_effort="low",
        messages=[
            AssistantMessage(content=rendered),
            UserMessage(content=user_message),
        ],
        sse_stream=sse_stream,
        max_complete_chat_tokens=800,
    )
