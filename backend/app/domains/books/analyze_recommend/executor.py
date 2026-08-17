"""The recommend node's flow. `run` is the table of contents; everything else
sits where the flow reaches it.

How this slice is laid out (the reading rule):

- **This file is the flow** — `run()` plus every *step* (anything awaited), as
  methods in the order `run` calls them. Pure helpers whose input needs no
  rendering are module-level functions here, also in flow order.
- **A satellite module is one LLM call's pure half** — `analyze_references.py`
  and `generate_response.py` each hold the rendering, the tool model and the
  request builder for one call, and nothing that runs. The arg parser has no
  rendering (the goal text *is* the message), so its builder lives here.
- **`dependents.py` is step 1's interpretation** — what the node makes of the
  anchors its input contract selected.
"""

import logging

from clients.messages import AssistantMessage
from common.prompts import basic_fill_schema_prompt
from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.schemas import Book
from clients import OpenAIParserRequest
from .dependents import ParsedDependents
from .analyze_references import (
    IdealBookDescription,
    build_analysis_request,
    render_documents,
)
from .generate_response import (
    build_response_request,
    render_summaries,
    summarize_references,
)
from .schemas import RecommendationStrategy
from .external import RecommendInput, RecommendationOutput
from airglider import task

logger = logging.getLogger(__name__)

MAX_ALLOWED_SAME_AUTHOR = 4
MAX_RECOMMENDED_BOOKS = 10


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `RecommendationStrategy` in from the goal text.

    Reads the user's own words, unlike `build_analysis_request` next door,
    which reads the documents the dependencies produced.
    """
    if not query:
        raise ValueError("No query to parse arguments from")

    return OpenAIParserRequest(
        prompt=basic_fill_schema_prompt,
        model="gpt-5-nano",
        reasoning_effort="minimal",
        # the goal text is the planner's own work, not something the user typed
        # NOTE: this should carry the previous messages too; clear and direct
        # instructions are enough while the conversation is single-turn.
        messages=[AssistantMessage(content=query)],
        tool_models=[RecommendationStrategy],
        # the goal already picked the node type and tool_choice pins it, so the
        # class docstring (there to help the planner choose) is noise here.
        # Field descriptions still ship.
        include_tool_description=False,
        max_completion_tokens=2000,
    )


def build_search_text(analyzed: str | None, user_input: str | None) -> str:
    """The text that gets embedded — the analyzed anchor plus whatever the
    user asked for on top. Either half can be missing: "books like X" has no
    twist, a purely thematic ask has no anchor."""
    return "\n\n".join(part for part in (analyzed, user_input) if part)


def rank_candidates(
    candidates: list[Book],
    references: list[Book],
    limit: int = MAX_RECOMMENDED_BOOKS,
    max_same_author: int = MAX_ALLOWED_SAME_AUTHOR,
) -> list[Book]:
    """Pick the books to recommend, in the store's similarity order.

    A pure function on purpose: "expandable later" means replacing this body
    (or swapping the function), not growing a strategy class now. Today's one
    rule is an author cap — "like Dune" should not be four more Herberts — and
    it applies however few candidates there are, not only past `limit`.
    """
    if not candidates:
        raise ValueError("No books were returned from embedding search")

    referenced_authors = {book.authors for book in references}
    same_author_count = 0
    picked: list[Book] = []
    for book in candidates:
        if book.authors in referenced_authors:
            if same_author_count >= max_same_author:
                continue
            same_author_count += 1
        picked.append(book)
        if len(picked) == limit:
            break
    return picked


class RecommendBooksExecutor(BookWorkflow[RecommendationOutput]):
    ui_loading_message = "Finding similar books..."
    ui_section_title = "Recommendation"
    # this node owns the answer — folding it away would hide the reply
    ui_section_collapsible = False

    async def run(self, node_input: RecommendInput) -> None:
        await self.sse_stream.send_ui_loading("recommending books...")

        # 1. collect artifacts — the input contract selected them, interpreting
        # them is this node's own job
        parsed_dependents = ParsedDependents.from_anchors(node_input.anchors)
        self.add_details(f"Dependents: {parsed_dependents.to_summary()}")
        if parsed_dependents.unknown:
            logger.warning(
                f"Ignoring anchors with neither rows nor a query: "
                f"{parsed_dependents.unknown}"
            )

        # rows a dependency already chose come through as-is; the rest of the
        # anchor is one composed query, run for rows here
        reference_books = list(parsed_dependents.books)
        if parsed_dependents.queries:
            result = await self.materialize_books(parsed_dependents.queries)
            reference_books += result.unwrap()
        self.result.references = reference_books

        # 2. parse the goal text into this node's own schema.
        # Two parsers, two inputs: the reference analyzer reads the documents
        # ("what is the anchor like"), the argument parser reads the user's own
        # words ("what did they ask for on top") — the twist and the bounds,
        # neither of which the documents can carry.
        parsed_args: RecommendationStrategy = await self.run_llm_args_parse(
            build_arg_parser_request(node_input.query)
        )
        self.result.args = parsed_args

        # 3. fold the references into an ideal-book description
        analyzed = (
            await self.analyze_references(reference_books, parsed_dependents.reports)
        ).unwrap()

        # 4. the filter builder goes here when the FilterBuilder slice exists —
        # `filters` re-grows on RecommendationStrategy the same day (schemas.py)

        # 5. assemble what gets embedded; either half can be missing, and this
        # is where sufficiency is judged — analyze_references returning None is
        # a missing input, an empty *sum* is a dead end
        search_text = build_search_text(analyzed, parsed_args.semantic_input)
        # kept apart from args.semantic_input on purpose — see RecommendationOutput
        self.result.search_text = search_text
        if not search_text:
            raise ValueError("Nothing to search on: no references and no semantic input")

        # 6. embed + search
        result = await self.similarity_search(
            search_text, exclude_isbns=[book.isbn13 for book in reference_books]
        )
        candidates = result.unwrap()

        # 7. rank — pure, no step
        recommended_books = rank_candidates(candidates, reference_books)
        self.result.books = recommended_books
        self.result.num_books = len(recommended_books)

        # 8. show, then tell
        await self.stream_books(recommended_books)
        await self.response_to_user(self.result)

        # 9. last, not before the reply: this node owns the answer, so a run
        # that found books and then failed to say anything about them is not ok
        self.finalize_result()

    @task
    async def analyze_references(
        self, books: list[Book], reports: list[str]
    ) -> str | None:
        """Fold the dependent books and reports into one description to embed.

        A `@task` so the two parser calls in `run` are distinguishable in the
        trace: this one's LLM step nests under a named envelope. Not a
        `Workflow` — the payload is a string, no declared output type to carry.

        None when there is nothing to fold: the producer completed, the input
        was missing (`ok=True`, empty payload). The user's own semantic_input
        may still carry the search; the caller judges sufficiency where the
        two halves meet.
        """
        document_text = render_documents(books, reports)
        if not document_text:
            self.add_details("No reference documents to analyze")
            return None

        req = build_analysis_request(document_text)
        analysis: IdealBookDescription = await self.run_llm_args_parse(req)
        self.add_details(
            f"Analyzed {len(books)} reference books and {len(reports)} reports "
            f"into {len(analysis.semantic_input.split())} words"
        )
        return analysis.semantic_input

    @task
    async def similarity_search(
        self, search_text: str, exclude_isbns: list[str]
    ) -> list[Book]:
        # a nested @task (the AppWorkflow wrapper — the client itself is
        # tracing-free): its envelope, with the embedding spend promoted onto
        # it, attaches under this one
        embedded = await self.get_embeddings([search_text])
        embedding = embedded.unwrap().embeddings[0]

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

    async def response_to_user(self, result: RecommendationOutput) -> None:
        """Write the note above the book cards, streamed as it is generated.

        The model gets two summaries and no book descriptions (see
        generate_response.py). The user's own phrasing comes off `result.args`;
        `result.search_text` is assembled anchor prose and is not sent.
        """
        input_summary = summarize_references(
            result.references, result.args.semantic_input if result.args else None
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

    def finalize_result(self):
        ok = self.result.args is not None and bool(self.result.books)
        return super().finalize_result(ok=ok)
