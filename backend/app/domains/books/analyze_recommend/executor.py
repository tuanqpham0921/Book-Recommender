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
from app.domains.books.filter_books import describe_bounds
from app.domains.books.schemas import Book
from clients import OpenAIParserRequest
from db.schema import BookMetadataFilter, ExclusionBookFilter
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
from .schemas import RecommendationArgs
from .external import RecommendInput, RecommendationOutput
from airglider import task

logger = logging.getLogger(__name__)

MAX_ALLOWED_SAME_AUTHOR = 4
MAX_RECOMMENDED_BOOKS = 10


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to decompose the goal text into `RecommendationArgs`.

    Reads the user's own words, unlike `build_analysis_request` next door,
    which reads the documents the dependencies produced. What comes back is a
    split rather than a fill, and the split is by where each part lands: the
    keywords join the embedded text, the bounds become WHERE clauses on the
    search, the exclusions are a predicate over what it returns.
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
        tool_models=[RecommendationArgs],
        max_completion_tokens=2000,
    )


def build_search_text(analyzed: str | None, user_input: str | None) -> str:
    """The text that gets embedded — the analyzed anchor plus whatever the
    user asked for on top. Either half can be missing: "books like X" has no
    twist, a purely thematic ask has no anchor."""
    return "\n\n".join(part for part in (analyzed, user_input) if part)


def excluded_by(book: Book, exclude: ExclusionBookFilter) -> bool:
    """Whether this book is one the ask ruled out by name.

    Casefolded substring both ways: the model writes "Herbert" where the column
    holds "Frank Herbert", and writes "Frank Herbert" where a co-authored row
    holds "Frank Herbert, Brian Herbert". `authors`, `categories` and `title`
    are each a single string on `Book`, so there is no list to walk.
    """
    fields = (
        (exclude.authors, book.authors),
        (exclude.categories, book.categories),
        (exclude.book_titles, book.title),
    )
    return any(
        any(term.casefold() in value.casefold() for term in terms if term)
        for terms, value in fields
        if terms and value
    )


def apply_exclusions(
    candidates: list[Book], exclude: ExclusionBookFilter | None
) -> list[Book]:
    """Drop the candidates the ask ruled out, keeping similarity order.

    In Python rather than in the search's WHERE, unlike the numeric bounds next
    to it: these are names the model wrote from the user's phrasing, and a
    forgiving substring match finds "Frank Herbert" from "Herbert" where SQL
    equality would quietly exclude nothing at all.

    Order survives because the list never leaves Python — which is the whole
    reason this node stopped handing its pool to the filter node, whose query
    would have come back ranked by rating.
    """
    if exclude is None:
        return candidates
    return [book for book in candidates if not excluded_by(book, exclude)]


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
            result = await self.fetch_anchor_books(parsed_dependents.queries)
            reference_books += result.unwrap()
        self.result.references = reference_books

        # 2. decompose the goal text into this node's three parts.
        # Two parsers, two inputs: the reference analyzer reads the documents
        # ("what is the anchor like"), this one reads the user's own words
        # ("what did they ask for on top") — the twist, the bounds and the
        # exclusions, none of which the documents can carry.
        parsed_args: RecommendationArgs = await self.run_llm_args_parse(
            build_arg_parser_request(node_input.query)
        )
        self.result.args = parsed_args

        # 3. fold the references into an ideal-book description
        analyzed = (
            await self.analyze_references(reference_books, parsed_dependents.reports)
        ).unwrap()

        # 4. assemble what gets embedded; either half can be missing, and this
        # is where sufficiency is judged — analyze_references returning None is
        # a missing input, an empty *sum* is a dead end.
        # The keywords rather than the raw goal text: "under 300 pages" in the
        # vector can only blur it, and that bound is carried by `bounds` below.
        search_text = build_search_text(analyzed, " ".join(parsed_args.keywords))
        # kept apart from args.keywords on purpose — see RecommendationOutput
        self.result.search_text = search_text
        if not search_text:
            raise ValueError("Nothing to search on: no references and no keywords")

        # 5. embed + search, with the bounds inside the search rather than
        # after it. The vector search does not select a subset — it orders the
        # whole table and truncates — so a bound applied afterwards cuts an
        # already-capped 50 and can leave two books. Applied here, the 50 that
        # come back all fit.
        bounds = describe_bounds(parsed_args.bounds) if parsed_args.bounds else ""
        if bounds:
            await self.sse_stream.send_ui_loading(f"limited to: {bounds}")
        result = await self.similarity_search(
            search_text,
            exclude_isbns=[book.isbn13 for book in reference_books],
            filters=parsed_args.bounds,
        )
        candidates = result.unwrap()

        # 6. the names the ask ruled out — pure, over the pool, and before the
        # ranking rather than after it: an exclusion applied to ten chosen
        # books deletes from the answer, applied here it only narrows what the
        # answer is chosen from.
        found = len(candidates)
        candidates = apply_exclusions(candidates, parsed_args.exclude)
        if found != len(candidates):
            self.add_details(f"{len(candidates)} of {found} candidates not excluded")

        # 7. rank — pure, no step. Only worth doing when there is a surplus to
        # choose from; below that the candidates already *are* the answer.
        if len(candidates) > MAX_RECOMMENDED_BOOKS * 1.5:
            await self.sse_stream.send_ui_loading("selecting best books...")
            recommended_books = rank_candidates(candidates, reference_books)
        else:
            recommended_books = candidates[:MAX_RECOMMENDED_BOOKS]

        self.result.books = recommended_books
        self.result.num_books = len(recommended_books)

        # 8. show, then tell — and tell even when there is nothing to show.
        # This node is the turn's answer, so a search that came back empty is a
        # sentence the user is owed ("nothing that short sits near those
        # books"), not a raise: raising would surface as the generic failure
        # message and say nothing about what was too tight.
        await self.stream_books(recommended_books)
        await self.response_to_user(self.result, bounds=bounds, found=found)

        # 9. last, not before the reply: this node owns the answer, so a run
        # that searched and then failed to say anything about it is not ok
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
        was missing (`ok=True`, empty payload). The user's own keywords may
        still carry the search; the caller judges sufficiency where the two
        halves meet.
        """
        await self.sse_stream.send_ui_loading("analyzing books...")

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
        self,
        search_text: str,
        exclude_isbns: list[str],
        filters: BookMetadataFilter | None = None,
        limit: int = 50,
    ) -> list[Book]:
        """The candidate pool: books near the embedded text that fit the bounds.

        Every narrowing goes into the one statement rather than onto its
        result. The store orders the whole table by distance and truncates at
        `limit`, so anything cut afterwards is cut from an already-capped 50 —
        which is how a page bound could leave two books to choose between.
        """
        # a nested @task (the AppWorkflow wrapper — the client itself is
        # tracing-free): its envelope, with the embedding spend promoted onto
        # it, attaches under this one
        await self.sse_stream.send_ui_loading("finding similar books...")

        embedded = await self.get_embeddings([search_text])
        embedding = embedded.unwrap().embeddings[0]

        rows = await self.store.search_by_embedding(
            embedding, filters=filters, exclude_isbns=exclude_isbns, limit=limit
        )
        return [Book.model_validate(row) for row in rows]

    @task
    async def response_to_user(
        self, result: RecommendationOutput, bounds: str = "", found: int = 0
    ) -> None:
        """Write the note above the book cards, streamed as it is generated.

        The model gets two summaries and no book descriptions (see
        generate_response.py). The user's own phrasing comes off `result.args`;
        `result.search_text` is assembled anchor prose and is not sent.

        `bounds` and `found` are the search's own account of itself, and they
        are what let the reply be honest when it is thin: the bounds as words
        the user will recognize, and how many candidates the search turned up
        before the exclusions ran. Zero recommendations is a reply this writes
        rather than an error — which is why they are passed in rather than read
        off `result`, where a bound that excluded everything leaves no trace.
        """
        input_summary = summarize_references(
            result.references,
            result.args.keywords if result.args else [],
            bounds=bounds,
            found=found,
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
        # ok means "the ask was parsed and answered", not "books were found".
        # An empty catalog match is an answer this node writes — the same way
        # `num_books == 0` is one for the filter node — so requiring `books`
        # here would mark a correct "nothing that short is near those" as a
        # failed goal. What is not ok is never getting as far as the reply.
        ok = self.result.args is not None
        return super().finalize_result(ok=ok)
