from typing import Any

from app.domains.node_executor import NodeExecutor
from app.domains.books.schemas import BookSummary
from app.orchestration.request_context import RequestContext
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.utils import compile_sql, compose
from .schemas import RecommendationOutput, RecommendationStrategy


class RecommendBooksExecutor(NodeExecutor[RecommendationOutput]):
    ui_loading_message = "Finding similar books..."
    ui_section_title = "Recommendation"
    # this node owns the answer — folding it away would hide the reply
    ui_section_collapsible = False
    tool_cls = RecommendationStrategy

    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        
        await self.sse_stream.send_ui_loading("recommending books...")

        

        

        # This is the terminal node today, so it is the one that runs SQL for
        # rows. Several depends_on ids mean "pool what all of these found"
        # (docs/design/execution-pipeline-v1.md) — an OR over the upstream
        # queries, composed into one WITH clause rather than intersected after
        # the fact.
        upstream = [
            result.query
            for result in dependent_results.values()
            if getattr(result, "query", None) is not None
        ]
        if upstream:
            await self._materialize(upstream, request_context)
            
        # walk through the dependents results
        # get all the queries and do a count first
        # if there are a lot then just pick the top 5
        # then use the descriptions to make a semantic input
        # we can deal with the compare or other analyze docs later
        parsed_args = await self.parse_arguments(query=query)
        # then do the similarity search


        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")

        self.finalize_result()

    async def _materialize(
        self,
        upstream: list[DeferredBookQuery],
        request_context: RequestContext,
    ) -> None:
        """Run the composed upstream query for rows, and stream them."""
        anchor = DeferredBookQuery(compose(upstream, op="or"), label="anchor")
        self.output.query = anchor
        self.output.query_sql = compile_sql(anchor.stmt)

        books = await request_context.book_store.materialize(
            anchor, limit=BookConstraints.default_limit
        )
        self.output.books = [BookSummary.model_validate(book) for book in books]
        self.output.num_books = len(books)

        # the answer, so the cards are worth streaming rather than dumping
        await self.stream_books(books, delay=0.2)

    def finalize_result(self):
        ok = self.output.args is not None
        return super().finalize_result(ok=ok, message="parsed args okay")
