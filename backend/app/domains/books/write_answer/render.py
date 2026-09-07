"""The answer call's pure half: a branch in, a request out.

`render_branch` turns the branch into the one block of text the writer reads,
and `build_answer_request` wraps it. Nothing here runs — the step that executes
the request is `AnswerWorkflow.write_answer`, next door.

The rendering is where the writer's whole world is decided, so two things stay
out of it. **Identifiers**: an isbn13 is not something to say in a sentence, and
a model that sees one will eventually print it. **Internal vocabulary**: the
steps are numbered and labelled by their goal description, never as "goals",
"nodes" or "queries" — the prompt forbids that language and the input should not
supply it either.
"""

from app.common.prompt_loader import load_prompt
from app.common.sse_stream import SSEStream
from app.common.utils import truncate_str
from app.domains.books.schemas import Book
from clients import OpenAIChatRequest
from clients.messages import AssistantMessage, UserMessage

from .external import AnswerStep

WRITE_ANSWER_PROMPT_PATH = "domains/books/write_answer/prompts/write_answer.txt"

# A blurb is context for one sentence about a book, not the book's whole entry.
MAX_DESCRIPTION_CHARS = 400
MAX_TOTAL_CHARS = 12000


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


def render_step(index: int, step: AnswerStep, books: list[Book]) -> str:
    """One step: what was asked, what came of it, and the books to prove it.

    The outcomes are rendered as different sentences rather than as a missing
    field, because "found none" and "could not run" are answers the reply has to
    tell apart — and a blank space tells them apart to nobody.

    The bare "completed" is the fourth: a step that produced an output this
    stage cannot read books out of. No registered node does that today, so it
    stands in for a future non-book capability rather than being reachable now —
    but reporting it as "found nothing" would be a claim about the catalog that
    nothing checked.
    """
    header = f"[{index}] {step.description}"

    if step.failed:
        return f"{header}\ncould not be completed"
    if step.output is None:
        return f"{header}\ncompleted"
    if not step.num_books:
        return f"{header}\nfound nothing"

    lines = [header, f"found {step.num_books} book(s)"]
    if books:
        lines.append("\n".join(render_book(book) for book in books))
    return "\n".join(lines)


def render_branch(steps: list[AnswerStep], rows: list[list[Book]]) -> str:
    """The whole branch as one block, in the order the steps were given.

    `rows` is positional against `steps` — the executor fetched them, and only
    it knows which steps it could afford to materialize, so a step with an empty
    list here may still have matched books. That is why the count is rendered
    separately from the rows rather than inferred from them.
    """
    blocks = [
        render_step(i, step, books)
        for i, (step, books) in enumerate(zip(steps, rows), start=1)
    ]
    return truncate_str("\n\n".join(blocks), MAX_TOTAL_CHARS, collapse=False)


def build_answer_request(
    rendered: str, sse_stream: SSEStream, user_message: str
) -> OpenAIChatRequest:
    """Ask the LLM to write the branch's reply, streaming as it goes.

    `sse_stream` is required by `OpenAIChatRequest` and is the whole delivery
    mechanism: `OpenAIClient._chat_stream` pushes each `content.delta` to it, so
    the reply reaches the browser as it is written and the assembled text still
    comes back for the record.

    Two messages, and the split is the trust boundary. The rendered branch is an
    `AssistantMessage` because it is prior system work — matching what
    `find_similar_books` does with its documents — and the prompt tells the
    model to read it as data. The user's own text stays a `UserMessage`: it is
    the question being answered, and it goes last so the model is replying to it
    rather than continuing its own turn.

    A cheap model on purpose: this call writes prose from facts it was handed,
    which is not the job accuracy was bought for on the planner.
    """
    if not rendered.strip():
        raise ValueError("Nothing to write an answer from")

    return OpenAIChatRequest(
        prompt=load_prompt(prompt_path=WRITE_ANSWER_PROMPT_PATH),
        model="gpt-5-mini",
        reasoning_effort="low",
        messages=[
            AssistantMessage(content=f"What I found:\n\n{rendered}"),
            UserMessage(content=user_message),
        ],
        sse_stream=sse_stream,
        max_complete_chat_tokens=800,
    )
