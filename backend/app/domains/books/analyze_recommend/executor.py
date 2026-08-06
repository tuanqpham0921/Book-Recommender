import logging
from typing import Any, List, Dict

from app.domains.node_executor import NodeExecutor
from app.domains.books.schemas import BookSummary
from app.orchestration.request_context import RequestContext
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.utils import compile_sql, compose
from .analyze_references import (
    ParsedDependents,
    ReferenceAnalysis,
    build_analysis_request,
    render_documents,
)
from .schemas import RecommendationOutput, RecommendationStrategy

logger = logging.getLogger(__name__)


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
        # TODO: move this to the books base workflow
        self.store = request_context.book_store

        await self.sse_stream.send_ui_loading("recommending books...")

        parsed_dependents = ParsedDependents.from_results(dependent_results)
        self.add_details(f"Dependents: {parsed_dependents.to_summary()}")
        if parsed_dependents.unknown:
            logger.warning(
                f"Ignoring unreadable dependent results: {parsed_dependents.unknown}"
            )

        # rows a dependency already chose come through as-is; the rest of the
        # anchor is one composed query, run for rows here
        books = list(parsed_dependents.books)
        if parsed_dependents.queries:
            books += await self._materialize_books(parsed_dependents.queries)

        # Two parsers, two inputs. The reference analyzer reads the *documents*
        # and answers "what is the user's anchor like"; the argument parser
        # reads the user's *own words* and answers "what did they ask for on
        # top of it" — the twist ("but darker") and the measurable bounds. The
        # documents can't carry either, which is why the goal text goes here
        # and not into the combined block.
        parsed_args = await self.parse_arguments(query=query)
        semantic_input = await self.analyze_references(books, parsed_dependents.reports)

        search_text = self.build_search_text(semantic_input, parsed_args.semantic_input)
        if not search_text:
            raise ValueError("Nothing to search on: no references and no semantic input")

        # then do the similarity search
        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")

        recommended_books = await self.similarity_search(
            search_text, exclude_isbns=[book.isbn13 for book in books]
        )
        self.output.books = recommended_books
        self.output.num_books = len(recommended_books)

        rows = [book.model_dump() for book in recommended_books]

        await self.response_to_user(recommended_books, books)
        await self.stream_books(rows)

        self.finalize_result()

    async def analyze_references(
        self, books: list[BookSummary], reports: list[str]
    ) -> str | None:
        """Fold the dependent books and reports into one description to embed.

        Returns None when there is nothing to fold — a node with no readable
        dependency still has the user's own semantic_input to search on, so
        this is a missing input, not a failure.
        """
        document_text = render_documents(books, reports)
        if not document_text:
            self.add_details("No reference documents to analyze")
            return None

        req = build_analysis_request(document_text)
        analysis: ReferenceAnalysis = await self.run_llm_args_parse(req)
        self.add_details(
            f"Analyzed {len(books)} reference books and {len(reports)} reports "
            f"into {len(analysis.semantic_input.split())} words"
        )
        return analysis.semantic_input

    @staticmethod
    def build_search_text(analyzed: str | None, user_input: str | None) -> str:
        """The text that actually gets embedded — the analyzed anchor, plus
        whatever the user asked for on top of it. Either half can be missing:
        a bare "books like X" has no twist, and a purely thematic ask has no
        anchor to analyze."""
        return "\n\n".join(part for part in (analyzed, user_input) if part)

    async def response_to_user(self, recommended_books, referenced_books):
        # TODO: generate a user response here with LLM
        
        from playground.app_mock.executors.books.recommend_books import mock_reply
        await self.sse_stream.send_chars(
            mock_reply
        )

    async def similarity_search(self, search_text: str, exclude_isbns: list[str]):
        embedding = await self.llm_client.get_embeddings([search_text])
        embedding = embedding[0]

        # TODO: push exclude_isbns into search_by_embedding as a NOT IN — the
        # references are what the user already named, so returning them is the
        # one answer we know is wrong. Filtered here meanwhile, which shrinks
        # the result set below `limit` instead of backfilling it.
        rows = await self.store.search_by_embedding(embedding)
        excluded = set(exclude_isbns)
        books = [
            BookSummary.model_validate(row)
            for row in rows
            if row.get("isbn13") not in excluded
        ]
        return books

    # TODO: this is re-usable should be in a workflow
    # for analyze nodes
    # maybe make a seperate book workflow
    async def _materialize_books(
        self, upstream: list[DeferredBookQuery]
    ) -> List[BookSummary]:
        """Run the composed upstream query for rows, and stream them."""
        anchor = DeferredBookQuery(compose(upstream, op="or"), label="anchor")
        self.output.query = anchor
        self.output.query_sql = compile_sql(anchor.stmt)

        num_books = await self.store.count(anchor)
        self.add_details(f"Dependent results has {num_books} books in total")
        if num_books > 5:
            ...
            # TODO: for now, re-query and only get the top rated
            # or give the users pre-defined options (random, ...)
            raise NotImplementedError("need to handle when there are more than 5 books")

        rows = await self.store.materialize(anchor, limit=BookConstraints.default_limit)
        books = [BookSummary.model_validate(row) for row in rows]
        return books

    def finalize_result(self):
        ok = self.output.args is not None
        return super().finalize_result(ok=ok, message="parsed args okay")
