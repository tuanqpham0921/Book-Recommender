import logging
from typing import Any, List
from pydantic import BaseModel

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
from dataclasses import dataclass, field
from collections import Counter

logger = logging.getLogger(__name__)

MAX_ALLOWED_SAME_AUTHOR = 4
MAX_RECOMMENDED_BOOKS = 10

class ReferenceBook(BaseModel):
    isbn13: str
    title: str
    authors: str | None = None
    categories: str | None = None
    genre: str | None = None
    is_children: bool | None = None
    description: str | None = None
    

@dataclass
class RecommendationArguments:
    refereced_books: list[ReferenceBook] = field(default_factory=list)
    semantic_input: str | None = None
    
    def to_summary(self):
        titles = [book.title for book in self.books]
        authors = [book.authors for book in self.books]
        author_num = Counter(authors)
        genres = [book.genre for book in self.books]
        genre_num = Counter(genres)
        return {
            "referenced_titles": titles, 
            "refrence_authors": authors,
            "refrence_author_num": author_num,
            "refrence_genre": genres,
            "refrence_genre_num": genre_num,
            "embedding_query": self.semantic_input
        }
        
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
        
        # TODO: automatically make an args
        # dataclass should be fine. Might put it in the class fields
        self.output.args = RecommendationArguments()
        
        await self.sse_stream.send_ui_loading("recommending books...")

        parsed_dependents = ParsedDependents.from_results(dependent_results)
        self.add_details(f"Dependents: {parsed_dependents.to_summary()}")
        if parsed_dependents.unknown:
            logger.warning(
                f"Ignoring unreadable dependent results: {parsed_dependents.unknown}"
            )

        # rows a dependency already chose come through as-is; the rest of the
        # anchor is one composed query, run for rows here
        reference_books = list(ReferenceBook(**book) for book in parsed_dependents.books)
        if parsed_dependents.queries:
            reference_books += await self._materialize_books(parsed_dependents.queries)
        self.output.args = reference_books
        
        # Two parsers, two inputs. The reference analyzer reads the *documents*
        # and answers "what is the user's anchor like"; the argument parser
        # reads the user's *own words* and answers "what did they ask for on
        # top of it" — the twist ("but darker") and the measurable bounds. The
        # documents can't carry either, which is why the goal text goes here
        # and not into the combined block.
        
        parsed_args = await self.parse_arguments(query=query)
        semantic_input = await self.analyze_references(reference_books, parsed_dependents.reports)

        # NOTE: parsed_args.semantic_input might not be needed
        search_text = self.build_search_text(semantic_input, parsed_args.semantic_input)
        self.output.args.semantic_input = search_text
        if not search_text:
            raise ValueError("Nothing to search on: no references and no semantic input")

        # then do the similarity search
        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")

        candidates = await self.similarity_search(
            search_text, exclude_isbns=[book.isbn13 for book in reference_books]
        )
        recommended_books = self.process_candidates(candidates)
        self.output.books = recommended_books
        self.output.num_books = len(recommended_books)

        rows = [book.model_dump() for book in recommended_books]

        await self.stream_books(rows)

        self.finalize_result()
        
        # ---------------------------
        # NOTE: this should be in a generation section(?)
        # putting this here for now
        await self.response_to_user(self.output)

    async def analyze_references(
        self, books: list[ReferenceBook], reports: list[str]
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

    async def response_to_user(self, result: RecommendationOutput):
        """ Generate an llm response to the user """
        
        inputs  = result.args.to_summary()
        output  = result.books.to_summary()

        format_result = (
                            f"input: {str(inputs)}\n",
                            f"output: {str(output)}\n"
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
    ) -> List[ReferenceBook]:
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

        # TODO: for now can just do the preview with top 5
        # and just log the book
        rows = await self.store.materialize(anchor, limit=BookConstraints.default_limit)
        books = [ReferenceBook(**row) for row in rows]
        return books
    
    def process_candidates(self, candidates: list[BookSummary], referenced_books: list[ReferenceBook]) -> list[BookSummary]:
        if not candidates:
            raise ValueError("No books were returned from embedding search")
        if len(candidates) <= MAX_RECOMMENDED_BOOKS:
            return candidates
        
        referenced_authors = set(book.author for book in referenced_books)
        same_author_count = 0
        recommended_books = []
        for book in candidates:
            if book.authors in referenced_authors:
                if same_author_count < MAX_ALLOWED_SAME_AUTHOR:
                    recommended_books.append(book)
                    same_author_count += 1
            else:
                recommended_books.append(book)
        return recommended_books
        

    def finalize_result(self):
        ok = self.output.args is not None and self.output.books
        return super().finalize_result(ok=ok, message="parsed args okay")
