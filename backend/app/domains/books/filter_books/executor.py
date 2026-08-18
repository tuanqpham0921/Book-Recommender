"""The filter node's flow — a single-call node that starts from a dependency.

Same four-file shape as `find_by_title/` (parse args → build the query → count
→ preview → finalize); the one addition is step 1, reading the query to narrow
off the anchors its input contract selected. That stays a module-level function
here rather than a `dependents.py`: there is one thing to pull out of an
anchor, which has not outgrown `run`.
"""

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.external import BookRetrievalOutput
from clients import OpenAIParserRequest
from db.schema import BookMetadataFilter
from db.stores import DeferredBookQuery

from .schemas import FilterRetrieval
from .external import FilterRetrievalInput, FilterRetrievalOutput

from common.prompts import basic_fill_schema_prompt


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FilterRetrieval` in from the goal text."""
    if not query:
        raise ValueError("No query to parse arguments from")

    return OpenAIParserRequest(
        prompt=basic_fill_schema_prompt,
        model="gpt-5-nano",
        reasoning_effort="minimal",
        # the goal text is the planner's own work, not something the user typed.
        # NOTE: this should carry the previous messages too; clear and direct
        # instructions are enough while the conversation is single-turn.
        messages=[AssistantMessage(content=query)],
        tool_models=[FilterRetrieval],
        # The goal already picked the node type and tool_choice pins it, so the
        # class docstring — which is there to help the planner choose between
        # tools — would only be noise here. Field descriptions still ship.
        include_tool_description=False,
        max_completion_tokens=2000,
    )


def anchor_queries(anchors: list[BookRetrievalOutput]) -> list[DeferredBookQuery]:
    """The queries this node can narrow, out of what its dependencies produced.

    An anchor with rows and no query is a node that *chose* its books
    (`RecommendationOutput`), and narrowing a ranked choice after the fact is
    what this node's docstring sends to `Analyze_Recommend.filters` instead. So
    it is dropped here rather than half-honored, and a goal left with nothing
    to narrow says so in `run`.
    """
    return [anchor.query for anchor in anchors if anchor.query is not None]


def describe_bounds(filters: BookMetadataFilter) -> str:
    """The bounds as the user-facing line, e.g. `min_pages=400, max_year=2000`.
    Only what the parse actually set — every other field is None."""
    return ", ".join(
        f"{name}={value}" for name, value in filters.model_dump(exclude_none=True).items()
    )


class FilterRetrievalExecutor(BookWorkflow[FilterRetrievalOutput]):
    ui_loading_message = "Narrowing the results..."
    ui_section_title = "Filtered books"

    async def run(self, node_input: FilterRetrievalInput) -> None:
        """Narrow the upstream query in SQL and hand the narrowed query on.

        Filtering the query rather than a fetched list is what keeps the count
        honest: it is over the whole upstream match, not over the handful of
        rows a preview happened to show.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        # 1. what this node was given — selection was the input contract's job,
        # interpreting it is this node's
        upstream = anchor_queries(node_input.anchors)
        self.add_details(
            f"{len(upstream)} of {len(node_input.anchors)} anchors carry a query"
        )
        if not upstream:
            raise ValueError(
                "Nothing to narrow: the anchors carry chosen books rather than a "
                "query, and bounds on a chosen set belong on the node that chose it"
            )

        # 2. parse the goal text into this node's own schema
        parsed_args: FilterRetrieval = await self.run_llm_args_parse(
            build_arg_parser_request(node_input.query)
        )
        self.result.args = parsed_args

        bounds = describe_bounds(parsed_args.filters)
        await self.sse_stream.send_ui_loading(f"filtering by: {bounds}")

        # 3. pool (several depends_on are an implicit union) and narrow — still
        # no rows: the bounds go into the query the count runs over
        anchor = DeferredBookQuery.compose(upstream, label="to_filter")
        deferred = self.store.filter_query(anchor, parsed_args.filters)
        total = (await self.count_books(deferred)).unwrap()

        await self.sse_stream.send_chars(f"- {total} books left after {bounds}")

        # 4. Cards for the section, streamed and let go — what travels
        # downstream is the narrowed query on `self.result`. Skipped entirely
        # when the bounds left nothing.
        if total:
            preview = await self.preview_books(deferred)
            await self.stream_books(preview.unwrap())

        # 5. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the bounds were parsed and applied", not "something
        # survived them" — an empty result is an answer this node reports.
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
