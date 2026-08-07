from typing import Any

from app.domains.books.base_workflow import BookBaseWorkflow
from .schemas import FindByTitleOutput, FindByTitleRetrieval


class FindByTitleExecutor(BookBaseWorkflow[FindByTitleOutput]):
    ui_loading_message = "Getting Book By Title..."
    ui_section_title = "Found books by title"
    tool_cls = FindByTitleRetrieval

    async def execute(self, query: str, dependent_results: dict[str, Any]) -> None:
        """Count the matching titles and hand the query downstream — not the set.

        The count is what makes a "4,000 matched, narrow it down?" pause
        possible before any large result set is built; the query is what lets
        a later node compose this search with another one in SQL instead of
        intersecting two already-capped lists.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)
        parsed_args = await self.parse_arguments(query=query)
        book_title = parsed_args.title
        if not book_title:
            raise ValueError("No title was parsed")
        await self.sse_stream.send_ui_loading(f"finding book titled: {book_title}")

        deferred = self.store.title_query(title=book_title)
        total, books = await self.preflight(deferred)

        # a sample, not the answer — `num_books` is the size of the match, and
        # the gap between the two is what marks these rows as a preview
        self.output.books = books

        await self.sse_stream.send_chars(
            f"- Found {total} books titled: {book_title}"
        )
        await self.stream_books(books)

        self.finalize_result()

    def finalize_result(self):
        # ok means "the query got built", not "something matched" — zero
        # matches is an answer this node reports, not a failure it raises.
        ok = self.output.args is not None and self.output.query is not None
        return super().finalize_result(ok=ok)
