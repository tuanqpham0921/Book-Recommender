"""The title node's flow — the worked example of a **single-call node**.

The 1-1 shape: one request schema, one executor, one LLM call (the arg parse),
then the counts-first opening move — nothing to interpret from upstream, so no
satellite modules. A slice that grows past this (several LLM calls, artifacts
to interpret) graduates to the layout `find_similar_books/` demonstrates; the
reading rule for both is in domains/README.md.
"""

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from clients import OpenAIParserRequest

from .schemas import FindByTitleArgs
from .external import FindByTitleInput, FindByTitleOutput

from common.prompts import basic_fill_schema_prompt


def build_arg_parser_request(instruction: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FindByTitleArgs` in from the planner's instruction."""
    if not instruction:
        raise ValueError("No instruction to parse arguments from")

    return OpenAIParserRequest(
        prompt=basic_fill_schema_prompt,
        model="gpt-5-nano",
        reasoning_effort="minimal",
        # the instruction is the planner's own work, not something the user typed.
        # NOTE: this should carry the previous messages too; clear and direct
        # instructions are enough while the conversation is single-turn.
        messages=[AssistantMessage(content=instruction)],
        tool_models=[FindByTitleArgs],
        max_completion_tokens=2000,
    )


class FindByTitleExecutor(BookWorkflow[FindByTitleOutput]):
    ui_loading_message = "Getting Book By Title..."
    ui_section_title = "Found books by title"

    async def run(self, node_input: FindByTitleInput) -> None:
        """Count the matching titles and hand the query downstream — not the set.

        The count is what makes a "4,000 matched, narrow it down?" pause
        possible before any large result set is built; the query is what lets
        a later node compose this search with another one in SQL instead of
        intersecting two already-capped lists.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. parse the goal text into this node's own schema
        instruction = node_input.instruction
        parsed_args: FindByTitleArgs = await self.run_llm_args_parse(
            build_arg_parser_request(instruction)
        )
        self.result.args = parsed_args

        book_title = parsed_args.title
        if not book_title:
            raise ValueError("No title was parsed")
        await self.sse_stream.send_ui_loading(f"finding book titled: {book_title}")

        # 2. build the deferred query and count — no rows fetched
        deferred = self.store.title_query(title=book_title)
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(
            f"- Found {total} books titled: {book_title}"
        )

        # 3. Cards for the section, kept on the output as `preview` for the
        # record and the reply. What travels downstream is still the query on
        # `self.result`, which reaches the whole match rather than these few
        # rows. Skipped entirely when nothing matched.
        if total:
            self.result.preview = (await self.fetch_books(deferred)).unwrap()
            await self.stream_books(self.result.preview)

        # 4. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the query got built", not "something matched" — zero
        # matches is an answer this node reports, not a failure it raises.
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
