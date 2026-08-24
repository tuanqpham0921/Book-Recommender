"""The numeric-traits node's flow — the single-call shape, same as `find_by_author/`.

One request schema, one executor, one LLM call (the arg parse), then the
counts-first opening move: nothing to interpret from upstream, so no satellite
modules — `describe_bounds` and `range_phrase` are pure and sit module-level
beside the flow, the same place `find_by_lexical_traits` keeps
`describe_lexical_traits`. The template and the reading rule are in
domains/README.md.

The one thing this node does that the other retrievals don't is turn words into
numbers — "well rated" into `min_rating: 4.0`. None of that lives here: the
mapping is on `BookMetadataFilter`'s field descriptions, which ship as part of
this node's tool schema, so the parse call is the same shape as every other.
"""

from collections.abc import Callable
from typing import Any

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from clients import OpenAIParserRequest
from db.schema import BookMetadataFilter

from .schemas import FindByNumericTraitsArgs
from .external import FindByNumericTraitsInput, FindByNumericTraitsOutput

from app.common.prompt_loader import load_prompt

ARGS_PARSER_PROMPT_PATH = (
    "domains/books/find_by_numeric_traits/prompts/numeric_traits_args_parser.txt"
)


def range_phrase(
    low: float | None,
    high: float | None,
    only_low: str,
    only_high: str,
    both: str,
    fmt: Callable[[Any], str] = str,
) -> str | None:
    """One bounded dimension as words, or None when it was left unbounded.

    Every numeric bound on `BookMetadataFilter` comes in a min/max pair with
    the same three cases, so the phrasing is a template per case rather than a
    branch per field — the four call sites below read as the four sentences
    the user will see.
    """
    if low is not None and high is not None:
        return both.format(low=fmt(low), high=fmt(high))
    if low is not None:
        return only_low.format(low=fmt(low))
    if high is not None:
        return only_high.format(high=fmt(high))
    return None


def describe_bounds(filters: BookMetadataFilter) -> str:
    """The bounds as the user-facing line, e.g. `300 pages or more, published
    between 2020 and 2022, not for children`.

    Only what the parse actually set — every other field is None, and an
    all-None filter is what `run` reads to refuse the goal. The words are the
    point: this string is read twice by the user (the loading message and the
    count line) and never by anything else, so it says what the bounds mean
    rather than which fields carry them. Both ends are inclusive, which is why
    every phrase is "or more"/"or fewer" rather than "over"/"under".

    Private to this slice, like `describe_lexical_traits` is to its own. It was
    shared with `filter_books` until 2026-08-24, when that slice was replaced by
    `Combine_Intersect` and this became the only node that parses these bounds.
    """
    parts = [
        range_phrase(
            filters.min_pages,
            filters.max_pages,
            "{low} pages or more",
            "{high} pages or fewer",
            "between {low} and {high} pages",
        ),
        range_phrase(
            filters.min_year,
            filters.max_year,
            "published in {low} or later",
            "published in {high} or earlier",
            "published between {low} and {high}",
        ),
        range_phrase(
            filters.min_rating,
            filters.max_rating,
            "rated {low} or higher",
            "rated {high} or lower",
            "rated between {low} and {high}",
            fmt=lambda value: f"{value:.1f}",
        ),
        range_phrase(
            filters.min_ratings_count,
            filters.max_ratings_count,
            "with at least {low} ratings",
            "with at most {high} ratings",
            "with between {low} and {high} ratings",
            fmt=lambda value: f"{value:,}",
        ),
    ]
    if filters.is_children is not None:
        parts.append("for children" if filters.is_children else "not for children")

    return ", ".join(part for part in parts if part)


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FindByNumericTraitsArgs` in from the goal text.

    Its own prompt rather than the shared `basic_fill_schema_prompt`, which is
    the reason every slice builds its own request. That prompt says "do not use
    prior knowledge" and "do not infer arguments that do not match the query" —
    correct for the parses that pull a title or an author out of a sentence, and
    the exact opposite of this node's job. Measured: under the shared prompt,
    "obscure books nobody has heard of" and "something really long" both parsed
    to an empty filter, because the model was obeying it. Literal numbers were
    unaffected, which is what made the failure look like a schema problem.
    """
    if not query:
        raise ValueError("No query to parse arguments from")

    return OpenAIParserRequest(
        prompt=load_prompt(prompt_path=ARGS_PARSER_PROMPT_PATH),
        model="gpt-5-nano",
        # `low` rather than the `minimal` the other parses use, and the one
        # setting here that was arrived at by measurement instead of by copying
        # the template. On the eight-phrase calibration set, nano/minimal got
        # 2/8 and nano/low got 8/8; mini bought nothing over nano at either
        # effort, so the model stays the cheap one. Minimal does not merely miss
        # here, it corrupts: "fewer than 200 pages" came back as `min_pages:200,
        # max_ratings_count:1000`, a bound off a different phrase entirely.
        # Every other parse in the app extracts a value that is present in the
        # text; this one has to map a word onto a number, and that is the step
        # minimal cannot take.
        reasoning_effort="low",
        # the goal text is the planner's own work, not something the user typed.
        # NOTE: this should carry the previous messages too; clear and direct
        # instructions are enough while the conversation is single-turn.
        messages=[AssistantMessage(content=query)],
        tool_models=[FindByNumericTraitsArgs],
        max_completion_tokens=2000,
    )


class FindByNumericTraitsExecutor(BookWorkflow[FindByNumericTraitsOutput]):
    ui_loading_message = "Getting Books By Traits..."
    ui_section_title = "Found books by traits"

    async def run(self, node_input: FindByNumericTraitsInput) -> None:
        """Count the books inside the bounds and hand the query downstream.

        This is the retrieval most likely to match thousands of books — "well
        rated" alone is 42% of the catalog — which is exactly why it counts
        instead of fetching. The count next to the phrase the bounds were read
        as is what lets the user see that "well rated" landed on 2,190 books and
        say something narrower.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. parse the goal text into this node's own schema
        query = node_input.query
        parsed_args: FindByNumericTraitsArgs = await self.run_llm_args_parse(
            build_arg_parser_request(query)
        )
        self.result.args = parsed_args

        # An all-None filter is a parse that found nothing measurable, which
        # means this node was the wrong one for the goal. Caught here rather
        # than left to the store so the message names the goal, not the SQL.
        bounds = describe_bounds(parsed_args.traits)
        if not bounds:
            raise ValueError(
                "No measurable trait was parsed: this goal has nothing to search "
                "on, and bounds are all this node can search by"
            )
        await self.sse_stream.send_ui_loading(f"finding books: {bounds}")

        # 2. build the deferred query and count — no rows fetched
        deferred = self.store.numeric_traits_query(parsed_args.traits)
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(f"- Found {total} books: {bounds}")

        # 3. Cards for the section, and nothing more: they are streamed and
        # let go, never assigned to the output. What travels downstream is the
        # query on `self.result`, which reaches every book inside the bounds
        # rather than these few rows. Skipped entirely when nothing matched.
        if total:
            preview = await self.fetch_books(deferred)
            await self.stream_books(preview.unwrap())

        # 4. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the bounds were parsed and searched", not "something matched"
        # — bounds read from words are often tighter than the user pictured, and
        # reporting zero is how they learn that. Failing would tell them nothing
        # about which bound was too tight.
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
