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
what to look for next, and hand back a query for the pool nearest that
description. It does not rank the pool, drop books from it, or write the reply —
those are a later node's, and none of them exists yet. Handing on the *query*
rather than the rows is what leaves room for them: `Combine_Intersect` can bound
the pool in SQL and cosine order survives the narrowing.
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
from .external import ScoreStats, SimilarBooksInput, SimilarBooksOutput
from airglider import task

# How many named books get folded into one description. Past this the node
# refuses rather than averaging: five blurbs describe a taste, twenty describe
# nothing. The ceiling is the fetch size too, so below it the anchor is fetched
# whole rather than sampled — the count and the rows describe the same set.
MAX_ANCHOR_BOOKS = 5

# How many books the vector search keeps. A pool for a later node to narrow or
# re-rank, not a list for a person to read — so it is sized against what comes
# *after* it rather than against a screen. ~5% of the 5,197-row catalog: big
# enough that a downstream bound ("under 300 pages") still has a real pool to
# cut, which 50 was not — most books near any given anchor are long, so a bound
# over 50 could leave two. Small enough that "nothing in the 250 nearest passes"
# is an answer about the request rather than an artifact of the cap.
CANDIDATE_POOL_SIZE = 250


class FindSimilarBooksExecutor(BookWorkflow[SimilarBooksOutput]):
    ui_loading_message = "Finding similar books..."
    ui_section_title = "Similar books"

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

        # 4. embed + build. The named books are excluded from their own results
        # in SQL, so the excluded rows do not eat pool slots. Nothing is fetched
        # here — what comes back is the query, like every other retrieval.
        pool = (
            await self.build_pool(
                analyzed, exclude_isbns=[book.isbn13 for book in references]
            )
        ).unwrap()

        # 5. size it. `pool_stats` rather than `count_books`: this query counts
        # its own LIMIT, so the spread of `score` is what says whether the pool
        # is any good, and one aggregate answers both.
        total = (await self.pool_stats(pool)).unwrap()

        # 6. cards for the section: a preview, the same handful every other node
        # shows, kept on the output for the record and the reply. The pool
        # itself travels as `query` for a later node to narrow — an empty one
        # is a real answer, not a failure.
        if total:
            self.result.preview = (
                await self.fetch_books(pool, BookConstraints.default_limit)
            ).unwrap()
            await self.stream_books(self.result.preview)

        # 7. last: ok is read off the output
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
        # TODO: caching for dev
        return "A witty, finely observed comedy of manners set in a tightly governed social world where marriage, reputation and property shape every visit and conversation. The plot unfolds through salons, country assemblies and polite calls as a pair of sharp-minded protagonists spar, misread and slowly reassess one another amid the pressures of family expectation and class-conscious neighbors. Much of the action is social choreography\u2014dinners, letters, dances, gossip and small humiliations\u2014where unsaid motives and restrained emotion carry more weight than dramatic outbursts. The tone is light, ironic and humane: the narrator gently exposes vanity and prejudice while remaining affectionate toward the characters\u2019 foibles. Conflicts are interpersonal and moral rather than violent, moving the cast toward clearer self-knowledge, humility and the renegotiation of pride and prejudice. This is a domestically scaled novel that rewards attention to dialogue and manners, offering sly social critique beneath an entertaining surface of romantic entanglement and corrective revelations."
        
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
    async def build_pool(
        self,
        search_text: str,
        exclude_isbns: list[str],
        limit: int = CANDIDATE_POOL_SIZE,
    ) -> DeferredBookQuery:
        """The pool: a query for the books nearest the embedded description.

        Embed, then build — the round trip in here is the embedding's, not the
        search's. `embedding_search_stmt` hands back a `DeferredBookQuery`
        whose `score` column is cosine similarity, which is what lets a
        downstream `Combine_Intersect` bound this pool without flattening its
        ranking (`compose(op="and")` carries the one `score` through;
        `materialize_stmt` orders by it).

        The one `DeferredBookQuery` that carries a LIMIT, because the search
        does not select a subset — it orders the whole table and truncates, so
        the cap *is* the pool. That is why an intersect against it reports "of
        the 250 nearest, N also match", and why *pooling* it with `"or"` is
        lossy; see `DeferredBookQuery`.

        Recorded here rather than by the count, and that is the reason this
        builder is not a store method: the vector renders as
        `embed(search_text)` rather than 1024 floats, and only this call site
        knows that label. `search_text` is not lost — it is this task's own
        `input` (see `@task` in airglider) and `SimilarBooksOutput.search_text`,
        so the label points at a value the record already holds twice.
        """
        # a nested @task (the AppWorkflow wrapper — the client itself is
        # tracing-free): its envelope, with the embedding spend promoted onto
        # it, attaches under this one
        await self.sse_stream.send_ui_loading("finding similar books...")

        embedded = await self.get_embeddings([search_text])
        embedding = embedded.unwrap().embeddings[0]

        return embedding_search_stmt(
            embedding, limit=limit, exclude_isbns=exclude_isbns
        )

    @task
    async def pool_stats(self, query: DeferredBookQuery) -> int:
        """Stamp the pool on the output and size it, in one round trip.

        What `count_books` does for every other node, except that node's count
        means something on its own. This one's does not: the query carries a
        LIMIT, so a COUNT reports `min(250, matches)` and says nothing about
        whether the 250 are close. `score_stats` answers both — the count and
        the cosine spread — for the same single aggregate.

        Not a method on `BookWorkflow` for that reason and one more: the SQL
        recorded here needs the `embed(search_text)` label, which `count_books`
        has no way to know. Composing the pieces in the node's own flow is what
        the base class says to do instead of growing a third helper on it.
        """
        self.result.query = query
        self.result.query_sql = compile_sql(
            query.stmt, embedding_as="embed(search_text)"
        )

        stats = await self.store.score_stats(query)
        # None is an empty pool, not a missing measurement — nothing cleared
        # the similarity floor, which is a real answer this node reports
        self.result.score = ScoreStats.model_validate(stats) if stats else None
        self.result.num_books = self.result.score.count if self.result.score else 0

        if self.result.score:
            self.add_details(
                f"pool of {self.result.num_books}, similarity "
                f"{self.result.score.min:.3f}–{self.result.score.max:.3f}"
            )
        return self.result.num_books

    def finalize_result(self):
        # ok means "the anchors were folded and the search ran", not "books
        # were found". An empty pool is an answer this node reports — nothing
        # in the catalog sits near what was named — so requiring `books` here
        # would mark a correct "there is nothing like this" as a failed goal.
        # What is not ok is never getting as far as the search.
        ok = self.result.search_text is not None
        return super().finalize_result(ok=ok)
