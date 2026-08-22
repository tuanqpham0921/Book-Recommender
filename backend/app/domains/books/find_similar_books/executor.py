"""The similarity node's flow. `run` is the table of contents; everything else
sits where the flow reaches it.

How this slice is laid out (the reading rule):

- **This file is the flow** — `run()` plus every *step* (anything awaited), as
  methods in the order `run` calls them. Pure helpers whose input needs no
  rendering are module-level functions here, also in flow order.
- **A satellite module is one LLM call's pure half** — `analyze_references.py`
  holds the rendering, the tool model and the request builder for the node's
  one LLM call, and nothing that runs.
- **`dependents.py` is step 1's interpretation** — what the node makes of the
  anchors its input contract selected.

The node does one thing: fold the books the user named into a description of
what to look for next, and hand back the pool nearest that description. It does
not rank the pool, drop books from it, or write the reply — those are a later
node's, and none of them exists yet.
"""

from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.schemas import Book
from config import BookConstraints
from db.stores import DeferredBookQuery, compile_sql, embedding_search_stmt
from .dependents import ParsedDependents
from .analyze_references import (
    IdealBookDescription,
    build_analysis_request,
    render_documents,
)
from .external import SimilarBooksInput, SimilarBooksOutput
from airglider import task

# How many named books get folded into one description. Past this the node
# refuses rather than averaging: five blurbs describe a taste, twenty describe
# nothing. The ceiling is the fetch size too, so below it the anchor is fetched
# whole rather than sampled — the count and the rows describe the same set.
MAX_ANCHOR_BOOKS = 5

# How many books come back from the vector search. A pool to choose from, sized
# for a later node to re-rank rather than for a person to read.
CANDIDATE_POOL_SIZE = 50


class FindSimilarBooksExecutor(BookWorkflow[SimilarBooksOutput]):
    ui_loading_message = "Finding similar books..."
    ui_section_title = "Similar books"
    # while nothing downstream writes a reply, these cards are the whole answer
    ui_section_collapsible = False

    async def run(self, node_input: SimilarBooksInput) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. interpret the anchors, then check them *before* spending a round
        # trip. Every anchor counted itself on the way here, so how many books
        # this comes to is known without asking the database again — which is
        # what let the old count-then-cap step disappear from BookWorkflow.
        parsed = ParsedDependents.from_anchors(node_input.anchors)
        self.add_details(f"anchors: {parsed.to_summary()}")
        self.check_anchors(parsed)

        # 2. materialize: rows a dependency already chose, plus the pooled
        # queries. The anchor SQL goes to `add_details` rather than onto the
        # output — it is what this node *depended on*, not what it produced.
        references = list(parsed.books)
        if parsed.queries:
            anchor = DeferredBookQuery.compose(
                parsed.queries, op="or", label="anchor"
            )
            self.add_details(f"Anchor query: {compile_sql(anchor.stmt)}")
            fetched = await self.fetch_books(anchor, limit=MAX_ANCHOR_BOOKS)
            references += fetched.unwrap()
        self.result.references = references

        # 3. fold the references into the one description that gets embedded.
        # Nothing else contributes to it — with no argument parse there is no
        # second half to fall back on, so a fold that comes back empty is the
        # end of the node rather than a missing input to work around.
        analyzed = (await self.analyze_references(references)).unwrap()
        self.result.search_text = analyzed
        if not analyzed:
            raise ValueError(
                "Nothing to search on: the anchor books carry no descriptions"
            )

        # 4. embed + search. The named books are excluded from their own
        # results in SQL, so the excluded rows do not eat pool slots.
        pool = (
            await self.similarity_search(
                analyzed, exclude_isbns=[book.isbn13 for book in references]
            )
        ).unwrap()
        self.result.books = pool
        self.result.num_books = len(pool)

        # 5. cards for the section: a preview, the same handful every other
        # node shows. The whole pool travels on the output for a later node to
        # choose from — an empty one is a real answer, not a failure.
        await self.stream_books(pool[: BookConstraints.default_limit])

        # 6. last: ok is read off the output
        self.finalize_result()

    def check_anchors(self, parsed: ParsedDependents) -> None:
        """Refuse an anchor this node cannot fold, before it fetches anything.

        Two refusals, and the trace tells them apart. Nothing to be similar to
        is a plan that ran correctly and found no books; too many books is a
        plan that found too much to average — five blurbs describe a taste,
        twenty describe nothing in particular.

        A method rather than a pure function because the piles are worth
        recording even when they do not stop the run: an anchor that matched
        nothing is dropped silently otherwise, and that is the first question
        asked when the pool comes back strange.
        """
        if parsed.empty:
            self.add_details(
                f"{len(parsed.empty)} anchor(s) matched no books: {parsed.empty}"
            )
        if parsed.unknown:
            self.add_details(
                f"Ignoring anchors with neither rows nor a query: {parsed.unknown}"
            )

        total = parsed.total()
        if not total:
            raise RuntimeError(
                f"No anchor books to be similar to. Every lookup came back "
                f"empty (empty: {parsed.empty}, unreadable: {parsed.unknown})."
            )
        if total > MAX_ANCHOR_BOOKS:
            raise RuntimeError(
                f"{total} anchor books is more than the {MAX_ANCHOR_BOOKS} this "
                f"node folds into one description"
            )

    @task
    async def analyze_references(self, books: list[Book]) -> str | None:
        """Fold the anchor books into one description to embed.

        A `@task` so the fold is its own envelope in the trace: the LLM step
        nests under it, and its spend is attributed to the fold rather than to
        the search that follows. Not a `Workflow` — the payload is a string,
        with no declared output type to carry.

        None when there is nothing to fold — anchor books that carry no
        `description` between them. The producer completed and the input was
        missing (`ok=True`, empty payload); `run` is where that becomes a dead
        end, because `run` is what knows there is no other half left.
        """
        await self.sse_stream.send_ui_loading("analyzing books...")

        document_text = render_documents(books)
        if not document_text:
            self.add_details("No reference documents to analyze")
            return None

        req = build_analysis_request(document_text)
        analysis: IdealBookDescription = await self.run_llm_args_parse(req)
        self.add_details(
            f"Analyzed {len(books)} reference books into "
            f"{len(analysis.semantic_input.split())} words"
        )
        return analysis.semantic_input

    @task
    async def similarity_search(
        self,
        search_text: str,
        exclude_isbns: list[str],
        limit: int = CANDIDATE_POOL_SIZE,
    ) -> list[Book]:
        """The pool: the books nearest the embedded description.

        Build, record, execute: `embedding_search_stmt` returns the statement
        rather than running it, so it can be recorded before the store touches
        it — the trace shows every narrowing that was actually applied. The
        vector itself renders as `embed(search_text)` rather than 1024 floats;
        `search_text` is not lost, it is this task's own `input` (see `@task`
        in airglider) and `SimilarBooksOutput.search_text`, so the label points
        at a value the record already holds twice.

        The search orders the whole table by distance and truncates at `limit`,
        which is why anything that would narrow the pool has to go into this
        statement rather than onto its result — a bound applied afterwards cuts
        an already-capped 50. Nothing narrows it today except `exclude_isbns`;
        a later node that wants bounds passes them to `embedding_search_stmt`,
        it does not filter what comes back.
        """
        # a nested @task (the AppWorkflow wrapper — the client itself is
        # tracing-free): its envelope, with the embedding spend promoted onto
        # it, attaches under this one
        await self.sse_stream.send_ui_loading("finding similar books...")

        embedded = await self.get_embeddings([search_text])
        embedding = embedded.unwrap().embeddings[0]

        stmt = embedding_search_stmt(
            embedding, exclude_isbns=exclude_isbns, limit=limit
        )
        self.add_details(
            f"Similarity search: {compile_sql(stmt, embedding_as='embed(search_text)')}"
        )
        rows = await self.store.search_similar(stmt)
        return [Book.model_validate(row) for row in rows]

    def finalize_result(self):
        # ok means "the anchors were folded and the search ran", not "books
        # were found". An empty pool is an answer this node reports — nothing
        # in the catalog sits near what was named — so requiring `books` here
        # would mark a correct "there is nothing like this" as a failed goal.
        # What is not ok is never getting as far as the search.
        ok = self.result.search_text is not None
        return super().finalize_result(ok=ok)
