from typing import Any

from app.domains.node_executor import NodeExecutor
from app.orchestration.request_context import RequestContext
from .schemas import FindByTitleOutput, FindByTitleRetrieval
from db.stores import BookStore

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
        # 3. do a query to db
        #    * build the statement
        #    * do a query with just count
        #    * populate the output with found numbers
        #    * return the CTE as a step
        # 4. finalize the output
        #    * check if there are atleast 1 book
        #    * maybe stamp on the UI with the reference book
        await self.sse_stream.send_ui_loading(self.ui_loading_message)
        parsed_args = await self.parse_arguments(query=query)
        book_title = parsed_args.title
        if not book_title:
            raise ValueError("No title was parsed")
        await self.sse_stream.send_ui_loading(f"finding book titled: {book_title}")
        
        results = await request_context.book_store.search_by_title(
            title=book_title
        )
        self.output.num_books = len(results)
        
        # TODO: post process result
        await self.sse_stream.send_chars(f"- Found {len(results)} books titled: {book_title}")
        await self._stream_books([results], request_context.sse_stream)
        
        self.finalize_result()
        
    def finalize_result(self):
        ok = self.output.args is not None and self.output.num_books
        return super().finalize_result(ok=ok)
        
        
