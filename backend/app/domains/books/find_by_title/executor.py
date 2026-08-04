from typing import Any

from app.domains.node_executor import NodeExecutor
from app.orchestration.request_context import RequestContext
from .schemas import FindByTitleOutput, FindByTitleRetrieval


class FindByTitleExecutor(NodeExecutor[FindByTitleOutput]):
    ui_loading_message = "Getting Book By Title..."
    tool_cls = FindByTitleRetrieval

    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        # 0. send a UI loading message
        # 1. call the args parser here
        # 2. Update the UI message to f"Getting book title: {...}"
        # 3. do a query to db
        #    * build the statement
        #    * do a qeury with just count
        #    * populate the output with found numbers
        #    * return the CTE as a step
        # 4. finalize the output
        #    * check if there are atleast 1 book
        #    * maybe stamp on the UI with the reference book
        await self.sse_stream.send_ui_loading("finding books by title")
        
        parsed_args = await self.parse_arguments(query=query)
    
        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")
        
        self.output.args = parsed_args
        self.finalize_result()
        
    def finalize_result(self):
        ok = self.output.args is not None
        return super().finalize_result(ok=ok, message="parsed args okay")
        
        
