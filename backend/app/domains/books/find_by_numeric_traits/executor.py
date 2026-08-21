"""The numeric-traits node's flow — the single-call shape, same as `find_by_author/`.

One request schema, one executor, one LLM call (the arg parse), then the
counts-first opening move: nothing to interpret from upstream, so no satellite
modules. The template and the reading rule are in domains/README.md.

The one thing this node does that the other retrievals don't is turn words into
numbers — "well rated" into `min_rating: 4.0`. None of that lives here: the
mapping is on `BookMetadataFilter`'s field descriptions, which ship as part of
this node's tool schema, so the parse call is the same shape as every other.
"""

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.filter_books import describe_bounds
from clients import OpenAIParserRequest

from .schemas import FindByNumericTraitsArgs
from .external import FindByNumericTraitsInput, FindByNumericTraitsOutput

from app.common.prompt_loader import load_prompt

ARGS_PARSER_PROMPT_PATH = (
    "domains/books/find_by_numeric_traits/prompts/numeric_traits_args_parser.txt"
)


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
            preview = await self.preview_books(deferred)
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
