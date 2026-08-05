from typing import Any, List, Dict

from app.domains.node_executor import NodeExecutor
from app.domains.books.schemas import BookSummary
from app.orchestration.request_context import RequestContext
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.utils import compile_sql, compose
from .schemas import RecommendationOutput, RecommendationStrategy
from dataclasses import dataclass, field

# NOTE: not sure if I need this whole structure
@dataclass
class RecommendationParsedDependents:
    books: list[BookSummary] # for actual books
    books_sql: list[DeferredBookQuery] = field(default_factory=[]) # deffered quries
    analyze_docs: list[str] = field(default_factory=[]) # for any analyzed docs already
    unknown: list[Any] = field(default_factory=[]) # dependent results we can reject

    def __init__(self, dependent_results: dict[str, Any]):
        self.books_sql = [
            result.query
            for result in dependent_results.values()
            if getattr(result, "query", None) is not None
        ]
        # TODO: other fields when you implment them
        # you can check if the types are allowed


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

        parsed_dependents = RecommendationParsedDependents(dependent_results)
        
        # TODO: need to dependent results as well
        books = await self._materialize_books(parsed_dependents.books_sql)

        # TODO: need to make this (?)
        # [
        #   system prompt:
        #   assistant_query: (need to have the filter parser here)
        #   semantic stuff?
        # ]
        # or have a seperate filter parser
        
        combined_query = self.build_semantic_query(books)
        # combined_query += f"\n {query}"

        print("----- combined query -------")
        print(combined_query)
        print("------------")

        parsed_args = await self.parse_arguments(query=combined_query)

        print("------ Parsed semantic input ------")
        print(parsed_args.semantic_input)
        print("------------")

        # then do the similarity search
        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")

        recommended_books = await self.similarity_search(parsed_args)
        self.output.books = recommended_books
        self.output.num_books = len(recommended_books)
        
        print("------ recommended books ------")
        print(f"recommended {len(recommended_books)}")
        rows = [book.model_dump() for book in recommended_books]
        
        # from common.utils import print_json
        # print_json(rows)
        
        print("------------")
        
        
        await self.response_to_user(recommended_books, books)
        await self.stream_books(rows)
        
        self.finalize_result()
        
    async def response_to_user(self, recommended_books, referenced_books):
        # TODO: generate a user response here with LLM
        
        from playground.app_mock.executors.books.recommend_books import mock_reply
        await self.sse_stream.send_chars(
            mock_reply
        )

    async def similarity_search(self, parsed_args):
        # TODO: ensure there isn't an large amount of text
        # TODO: put the reference books to exlucde in here
        embedding = await self.llm_client.get_embeddings([parsed_args.semantic_input])
        embedding = embedding[0]

        rows = await self.store.search_by_embedding(embedding)
        books = [BookSummary.model_validate(row) for row in rows]
        return books

    def build_semantic_query(self, books):
        # TODO: add in other books and analyze docs
        result = []
        for book in books:
            result.append(f"{book.title}: {book.description} \n")

        return "\n".join(result)

    # TODO: this is re-usable should be in a workflow
    # for analyze nodes
    # maybe make a seperate book workflow
    async def _materialize_books(
        self, upstream: list[DeferredBookQuery]
    ) -> List[Dict[str, Any]]:
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
