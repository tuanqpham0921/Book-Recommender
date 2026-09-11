"""The writing call's pure half: the turn's task results in, a request out.

`render_report` turns what the plan produced into the one block of text the
writer reads, and `build_recommendations_request` wraps it. Nothing here runs —
the step that executes the request is
`GenerateRecommendationsExecutor.write_recommendations`, next door.

The rendering is where the writer's whole world is decided. Each section is one
goal's `TaskResult` in three parts: a header (the goal's instruction), an
`<info>` block (how that part of the work ended and how it was done), and a
`<books>` block (the preview the node kept). Two lines are held:

- **No identifiers in the books.** An isbn13 is not something to say in a
  sentence, and a model that sees one will eventually print it, so
  `render_book` never renders one.
- **Internals are grounding, not vocabulary.** The `<info>` block deliberately
  carries the search arguments, what the goal cost and its SQL (2026-09-11):
  they say exactly what was searched for, which the instruction only
  paraphrases. The prompt tells the model to read them and never repeat them,
  and never to call anything a goal, node or query. Known leak: `compile_sql`
  inlines literals, so a similarity search's SQL carries the anchor ISBNs.
  SQL renders last, so the info cap usually cuts it, and the prompt's
  no-identifiers rule covers the rest. A goal that crashed adds its exception's
  message — the message only, never the type name or traceback — and the prompt
  turns it into a plain cause ("that isn't something I can do yet").

The report is evidence and nothing else. It used to open with a `What to write:`
brief — this stage's own goal instruction, the one line in the block the model
was told to obey — and that line went away with the goal (2026-09-08): an
unregistered stage has no planner text, so the *user's* message is the brief and
it travels as the `UserMessage` in `build_recommendations_request`.

**Each section is capped, not the report.** Truncating the joined block cut
from the end, and the end is where failures render. A section is bounded by its
parts — the instruction (`MAX_INSTRUCTION_LENGTH`), one `MAX_INFO_CHARS` block
and at most `BookConstraints.default_limit` books of `MAX_BOOK_CHARS` each — and
a plan by `MAX_SYSTEM_GOALS`, so the report needs no cap of its own.

One typed read reaches into a sibling slice: a source that is a
`SimilarBooksOutput` carries the anchor books it was built from and the
description it embedded, which are the actual "why these fit" material.
Interpretation of upstream shapes is the consuming stage's own job (rule 4 in
domains/README.md), and widening `BookCandidateOutput` so this stays
import-free would put two fields on a shared shape for one reader.
"""

import json

from app.common.prompt_loader import load_prompt
from app.common.sse_stream import SSEStream
from app.common.utils import truncate_str
from app.domains.base_workflow import FailedGoalOutput, NodeWorkflowOutput
from app.domains.books.external import BookRetrievalOutput
from app.domains.books.find_similar_books import SimilarBooksOutput
from app.domains.books.schemas import Book
from app.orchestration.task_runner import TaskResult
from airglider import remove_empty_values
from clients import OpenAIChatRequest
from clients.messages import AssistantMessage, UserMessage

PROMPT_PATH = "orchestration/write_recommendations/prompts/write_recommendations.txt"

# A section's two caps, in characters (~4 per token). The info block is
# grounding, so it is the one allowed to lose its tail; a book entry is sized so
# a catalog-average description (~500 chars) survives whole.
MAX_INFO_CHARS = 400
MAX_BOOK_CHARS = 600

# What an entry with no goal instruction is headed by — an output that never
# travelled through the runner, which no registered plan produces today.
FALLBACK_HEADER = "part of the search"

# what the evidence is headed by
FINDINGS_HEADER = "What I found:"


def render_book(book: Book) -> str:
    """One book as the writer sees it, at most `MAX_BOOK_CHARS`.

    Fields picked by hand, which is what `Book`'s docstring asks for instead of
    a narrower model. No isbn13 and no thumbnail: the first is an identifier the
    prose must never contain, the second already travelled to the browser on the
    card. The cap is on the whole entry, so the description gets whatever room
    the fact line leaves.
    """
    facts = [book.authors or "author unknown"]
    if book.published_year:
        facts.append(str(book.published_year))
    if book.num_pages:
        facts.append(f"{book.num_pages} pages")
    if book.average_rating:
        facts.append(f"rated {book.average_rating}")

    line = f"- {book.title} — {', '.join(facts)}"
    # the newline, the two-space indent and `truncate_str`'s ellipsis
    room = MAX_BOOK_CHARS - len(line) - 4
    if book.description and room > 0:
        line += f"\n  {truncate_str(book.description, room)}"
    return line


def render_outcome(output: NodeWorkflowOutput) -> str:
    """How one part of the work ended — the first line of its info block.

    Three endings, kept apart because they mean different things to the reply:
    "found nothing" is an answer about the catalog, rendered as a sentence
    because a blank relays it to nobody; "could not be completed" is about the
    plan, with the runner's reason relayed verbatim — it is already prose, and
    the only place a two-hop cause is stated.
    """
    if isinstance(output, FailedGoalOutput):
        line = "could not be completed"
        if output.reason:
            line += f" — {output.reason}"
        return line

    num_books = output.num_books if isinstance(output, BookRetrievalOutput) else 0
    return f"found {num_books} book(s)" if num_books else "found nothing"


def render_info(result: TaskResult) -> str:
    """How one part of the work went and how it was done, at most
    `MAX_INFO_CHARS`: the outcome, the error, the similarity lines, the
    arguments, what it cost, and the SQL — in that order, so the cap cuts the
    SQL first and never the error.

    The similarity pool gets two extra lines. Its books match a description the
    *system* wrote from the books the user named, and a reply explaining "why
    these fit" is only honest against that: what it was built from, and what
    was actually searched for.

    Read off the fields rather than `output.to_summary()`: that is the trace's
    view (`has_query`, a reference *count*), and changing it would change every
    `chat_runs` summary.
    """
    output = result.output
    lines = [render_outcome(output)]

    if result.error_message:
        lines.append(f"error: {result.error_message}")

    if isinstance(output, SimilarBooksOutput):
        if output.references:
            named = ", ".join(book.title for book in output.references)
            lines.append(f"built from the reader's reference books: {named}")
        if output.search_text:
            lines.append(f'searched for books matching: "{output.search_text}"')

    # `getattr`: every parsing slice types its own `args`, and no shared shape
    # declares the field
    args = getattr(output, "args", None)
    if args is not None:
        parsed = remove_empty_values(args.model_dump(mode="json"))
        if parsed:
            lines.append(f"arguments: {json.dumps(parsed, ensure_ascii=False)}")

    if result.duration is not None:
        cost = f"took {result.duration}s"
        if result.total_tokens:
            cost += (
                f", {result.total_tokens} tokens "
                f"({result.input_tokens} in, {result.output_tokens} out)"
            )
        lines.append(cost)

    if isinstance(output, BookRetrievalOutput) and output.query_sql:
        lines.append(f"sql: {' '.join(output.query_sql.split())}")

    return truncate_str("\n".join(lines), MAX_INFO_CHARS, collapse=False)


def render_section(index: int, result: TaskResult) -> str:
    """One goal: what was asked, how it went, and the books it kept.

    No `<books>` block when there are none — nothing matched, or the goal
    failed — rather than an empty one the model has to interpret.
    """
    output = result.output
    parts = [
        f"[{index}] {output.goal_instruction or FALLBACK_HEADER}",
        f"<info>\n{render_info(result)}\n</info>",
    ]

    books = output.preview if isinstance(output, BookRetrievalOutput) else []
    if books:
        rendered = "\n".join(render_book(book) for book in books)
        parts.append(f"<books>\n{rendered}\n</books>")

    return "\n".join(parts)


def render_report(results: list[TaskResult]) -> str:
    """Everything the plan produced as one block, a section per result, in the
    order given.

    Every section is evidence — there is no brief at the top, so nothing in
    this block is an instruction and the prompt can say so without an
    exception (see the module docstring).
    """
    blocks = [FINDINGS_HEADER]
    blocks += [
        render_section(i, result) for i, result in enumerate(results, start=1)
    ]
    return "\n\n".join(blocks)


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
