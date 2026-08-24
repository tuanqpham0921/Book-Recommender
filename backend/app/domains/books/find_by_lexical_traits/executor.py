"""The lexical-traits node's flow — the single-call shape, same as `find_by_title/`.

Parse the goal into lexical traits, build the deferred query, count, preview,
hand the query on. The one thing this node does that the other retrievals don't
is search *text* rather than a column: `BookStore.lexical_query` folds title,
shelf label and description into one tsvector, because `books.categories` holds a
single Google-Books shelf label per book and cannot answer "books about ninjas"
on its own. None of that lives here — the store owns the SQL, and this file owns
the order the steps happen in.
"""

from app.common.prompt_loader import load_prompt
from app.domains.books.base_workflow import BookWorkflow
from clients import OpenAIParserRequest
from clients.messages import AssistantMessage
from db.schema import AudienceEnum

from .external import FindByLexicalTraitsInput, FindByLexicalTraitsOutput
from .schemas import FindByLexicalTraitsArgs

ARGS_PARSER_PROMPT_PATH = (
    "domains/books/find_by_lexical_traits/prompts/lexical_traits_args_parser.txt"
)


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FindByLexicalTraitsArgs` in from the goal text.

    Its own prompt rather than the shared `basic_fill_schema_prompt`, for the
    reason the numeric-traits slice measured: the shared prompt's "do not infer"
    is the opposite of what this node needs from "children's books", which names
    no field but means `audience: children`. The inference here is narrow — a
    word to a shelf, never a word to a bound — so the prompt spends most of its
    length on what *not* to put in `keywords`.
    """
    if not query:
        raise ValueError("No query to parse arguments from")

    return OpenAIParserRequest(
        prompt=load_prompt(prompt_path=ARGS_PARSER_PROMPT_PATH),
        model="gpt-5-nano",
        reasoning_effort="low",
        messages=[AssistantMessage(content=query)],
        tool_models=[FindByLexicalTraitsArgs],
        max_completion_tokens=2000,
    )


_READERS: dict[AudienceEnum, str] = {
    AudienceEnum.CHILDREN: "children",
    AudienceEnum.ADULT: "adults",
}


def describe_lexical_traits(args: FindByLexicalTraitsArgs) -> str:
    """The traits as the user-facing line, e.g. `non-fiction about space, for children`.

    Only what the parse actually set; an all-empty args object returns "", which
    is what the executor reads to refuse the goal. The lexical counterpart of
    `describe_bounds`, and private to this slice where that one is not:
    `describe_bounds` is re-exported from `filter_books` only because the numeric
    node parses the same bounds, and nothing else parses these args.
    """
    subject = " and ".join(keyword for keyword in args.keywords if keyword.strip())
    readers = _READERS[args.audience] if args.audience else None

    if args.genre and subject:
        what = f"{args.genre.value} about {subject}"
    elif args.genre:
        what = f"{args.genre.value} books"
    elif subject:
        what = f"books about {subject}"
    elif readers:
        # audience alone still needs a noun, or the count line reads
        # "Found 447 for children"
        return f"books for {readers}"
    else:
        return ""

    return f"{what}, for {readers}" if readers else what


class FindByLexicalTraitsExecutor(BookWorkflow[FindByLexicalTraitsOutput]):
    ui_loading_message = "Searching The Catalog's Text..."
    ui_section_title = "Found books by keyword, shelf and audience"

    async def run(self, node_input: FindByLexicalTraitsInput) -> None:
        """Count the books matching the lexical traits and hand the query downstream."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. parse the goal text into this node's own schema
        query = node_input.query
        parsed_args: FindByLexicalTraitsArgs = await self.run_llm_args_parse(
            build_arg_parser_request(query)
        )
        self.result.args = parsed_args

        # An empty parse means no keyword, no shelf and no audience were found,
        # which means this node was the wrong one for the goal. Refused here,
        # naming the goal, rather than left to the store's ValueError, which can
        # only name the SQL.
        described = describe_lexical_traits(parsed_args)
        if not described:
            raise ValueError(
                "No lexical traits were parsed: this goal names no keyword, "
                "genre or audience, and those are all this node can search by"
            )
        await self.sse_stream.send_ui_loading(f"finding {described}")

        # 2. build the deferred query and count — no rows fetched
        deferred = self.store.lexical_query(
            keywords=parsed_args.keywords,
            genre=parsed_args.genre,
            audience=parsed_args.audience,
        )
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(f"- Found {total} {described}")

        # 3. Cards for the section, and nothing more: streamed and let go,
        # never assigned to the output.
        if total:
            preview = await self.fetch_books(deferred)
            await self.stream_books(preview.unwrap())

        # 4. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the traits were parsed and searched", not "something matched"
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
