from typing import Any

from app.domains.node_executor import NodeExecutor
from app.orchestration.request_context import RequestContext
from .schemas import FindByTitleOutput, FindByTitleRetrieval
from db.stores.utils import compile_sql

class FindByTitleExecutor(NodeExecutor[FindByTitleOutput]):
    ui_loading_message = "Getting Book By Title..."
    tool_cls = FindByTitleRetrieval

    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],

        # TODO: this can move to a book store workflow, __init__
        request_context: RequestContext,
    ) -> None:
        """Count the matching titles and hand the query downstream — no rows.

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

        store = request_context.book_store
        deferred = store.title_query(title=book_title)

        self.output.query = deferred
        self.output.query_sql = compile_sql(deferred.stmt)
        self.output.num_books = await store.count(deferred)

        await self.sse_stream.send_chars(
            f"- Found {self.output.num_books} books titled: {book_title}"
        )

        self.finalize_result()

    def finalize_result(self):
        # ok means "the query got built", not "something matched" — zero
        # matches is an answer this node reports, not a failure it raises.
        ok = self.output.args is not None and self.output.query is not None
        return super().finalize_result(ok=ok)


