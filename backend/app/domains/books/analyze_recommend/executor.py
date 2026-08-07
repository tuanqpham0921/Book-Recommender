import logging
from typing import Any, List

from app.domains.books.executor import BookNodeExecutor
from app.domains.books.schemas import Book
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.utils import compose
from .analyze_references import (
    ParsedDependents,
    ReferenceAnalysis,
    build_analysis_request,
    render_documents,
)
from .generate_response import (
    build_response_request,
    render_summaries,
    summarize_references,
)
from .schemas import RecommendationOutput, RecommendationStrategy

logger = logging.getLogger(__name__)

MAX_ALLOWED_SAME_AUTHOR = 4
MAX_RECOMMENDED_BOOKS = 10


class RecommendBooksExecutor(BookNodeExecutor[RecommendationOutput]):
    ui_loading_message = "Finding similar books..."
    ui_section_title = "Recommendation"
    # this node owns the answer — folding it away would hide the reply
    ui_section_collapsible = False
    tool_cls = RecommendationStrategy

    async def execute(self, query: str, dependent_results: dict[str, Any]) -> None:
        await self.sse_stream.send_ui_loading("recommending books...")

        parsed_dependents = ParsedDependents.from_results(dependent_results)
        self.add_details(f"Dependents: {parsed_dependents.to_summary()}")
        if parsed_dependents.unknown:
            logger.warning(
                f"Ignoring unreadable dependent results: {parsed_dependents.unknown}"
            )

        # rows a dependency already chose come through as-is; the rest of the
        # anchor is one composed query, run for rows here
        reference_books = list(parsed_dependents.books)
        if parsed_dependents.queries:
            reference_books += await self._materialize_books(parsed_dependents.queries)
        self.output.references = reference_books

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
        # kept apart from args.semantic_input on purpose — see RecommendationOutput
        self.output.search_text = search_text
        if not search_text:
            raise ValueError("Nothing to search on: no references and no semantic input")

        # then do the similarity search
        await self.sse_stream.send_chars(f"- loaded argument for {query}\n")

        candidates = await self.similarity_search(
            search_text, exclude_isbns=[book.isbn13 for book in reference_books]
        )
        recommended_books = self.process_candidates(candidates, reference_books)
        self.output.books = recommended_books
        self.output.num_books = len(recommended_books)

        await self.stream_books(recommended_books)

        # ---------------------------
        # NOTE: this should be in a generation section(?)
        # putting this here for now
        await self.response_to_user(self.output)

        # last, not before the reply: this node owns the answer, so a run that
        # found books and then failed to say anything about them is not ok
        self.finalize_result()

    async def analyze_references(
        self, books: list[Book], reports: list[str]
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

    async def response_to_user(self, result: RecommendationOutput) -> None:
        """Write the note that sits above the book cards, streaming it as it
        is generated.

        The model gets two summaries and no book descriptions — see
        generate_response.py for why. The user's own phrasing comes off
        `result.args`, which the argument parser filled and nothing since has
        touched; `result.search_text` is the assembled anchor prose and is
        deliberately not sent.
        """
        input_summary = summarize_references(
            result.references, getattr(result.args, "semantic_input", None)
        )
        summary_text = render_summaries(input_summary, result.to_summary())

        await self.sse_stream.send_ui_loading("writing up your recommendations...")
        req = build_response_request(summary_text, self.sse_stream)
        message = await self.run_llm_call(req)
        self.add_details(
            f"Wrote a {len((message.content or '').split())} word reply "
            f"from {len(result.references)} references and "
            f"{len(result.books)} recommendations"
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
            Book.model_validate(row)
            for row in rows
            if row.get("isbn13") not in excluded
        ]
        return books

    async def _materialize_books(
        self, upstream: list[DeferredBookQuery]
    ) -> List[Book]:
        """Pool the upstream queries into one anchor and fetch its books.

        `preflight` returns the size of the pool and the rows in a single round
        trip, so below the cap the sample *is* the anchor and there is nothing
        left to materialize separately. Note what it stamps on the output —
        `query`/`query_sql`/`num_books` describe the *references* here;
        `execute()` overwrites `num_books` with the recommendation's own count
        once it has one.
        """
        anchor = DeferredBookQuery(compose(upstream, op="or"), label="anchor")
        num_books, books = await self.preflight(
            anchor, sample=BookConstraints.default_limit
        )
        self.add_details(f"Dependent results has {num_books} books in total")
        if num_books > 5:
            # TODO: for now, re-query and only get the top rated
            # or give the users pre-defined options (random, ...)
            raise NotImplementedError("need to handle when there are more than 5 books")

        return books

    def process_candidates(self, candidates: list[Book], referenced_books: list[Book]) -> list[Book]:
        if not candidates:
            raise ValueError("No books were returned from embedding search")
        if len(candidates) <= MAX_RECOMMENDED_BOOKS:
            return candidates
        
        referenced_authors = set(book.authors for book in referenced_books)
        same_author_count = 0
        recommended_books = []
        for book in candidates:
            if book.authors in referenced_authors:
                if same_author_count < MAX_ALLOWED_SAME_AUTHOR:
                    recommended_books.append(book)
                    same_author_count += 1
            else:
                recommended_books.append(book)
            
            if len(recommended_books) == MAX_RECOMMENDED_BOOKS:
                break
                
        return recommended_books
        

    def finalize_result(self):
        ok = self.output.args is not None and bool(self.output.books)
        return super().finalize_result(ok=ok, message="parsed args okay")
