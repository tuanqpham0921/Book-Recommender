"""The author node's flow — the single-call shape, same as `find_by_title/`.

One request schema, one executor, one LLM call (the arg parse), then the
counts-first opening move: nothing to interpret from upstream, so no satellite
modules. The template and the reading rule are in domains/README.md.
"""

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from clients import OpenAIParserRequest

from .schemas import FindByAuthorArgs
from .external import FindByAuthorInput, FindByAuthorOutput

from common.prompts import basic_fill_schema_prompt


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FindByAuthorArgs` in from the goal text."""
    if not query:
        raise ValueError("No query to parse arguments from")

    return OpenAIParserRequest(
        prompt=basic_fill_schema_prompt,
        model="gpt-5-nano",
        reasoning_effort="minimal",
        # the goal text is the planner's own work, not something the user typed.
        # NOTE: this should carry the previous messages too; clear and direct
        # instructions are enough while the conversation is single-turn.
        messages=[AssistantMessage(content=query)],
        tool_models=[FindByAuthorArgs],
        max_completion_tokens=2000,
    )


class FindByAuthorExecutor(BookWorkflow[FindByAuthorOutput]):
    ui_loading_message = "Getting Books By Author..."
    ui_section_title = "Found books by author"

    async def run(self, node_input: FindByAuthorInput) -> None:
        """Count the author's books and hand the query downstream — not the set.

        A bibliography is the retrieval most likely to be large, so the count
        is what makes a "217 matched, narrow it down?" pause possible before
        any of it is built; the query is what lets a later node intersect this
        author with a title, or narrow it by metadata, in SQL rather than over
        two already-capped lists.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. parse the goal text into this node's own schema
        query = node_input.query
        parsed_args: FindByAuthorArgs = await self.run_llm_args_parse(
            build_arg_parser_request(query)
        )
        self.result.args = parsed_args

        author = parsed_args.author
        if not author:
            raise ValueError("No author was parsed")
        await self.sse_stream.send_ui_loading(f"finding books by: {author}")

        # 2. build the deferred query and count — no rows fetched
        deferred = self.store.author_query(author=author)
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(f"- Found {total} books by: {author}")

        # 3. Cards for the section, and nothing more: they are streamed and
        # let go, never assigned to the output. What travels downstream is the
        # query on `self.result`, which reaches the whole bibliography rather
        # than these few rows. Skipped entirely when nothing matched.
        if total:
            preview = await self.fetch_books(deferred)
            await self.stream_books(preview.unwrap())

        # 4. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the query got built", not "something matched" — an author
        # the catalog has never heard of is an answer this node reports, and
        # the whole point of the intersect that verifies an attribution.
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
