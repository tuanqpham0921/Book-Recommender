"""The filter node's flow — a single-call node that starts from a dependency.

Same four-file shape as `find_by_title/` (parse args → build the query → count
→ preview → finalize); the one addition is step 1, reading the query to narrow
off the anchors its input contract selected. That stays a module-level function
here rather than a `dependents.py`: there is one thing to pull out of an
anchor, which has not outgrown `run`.
"""

from collections.abc import Callable
from typing import Any

from clients.messages import AssistantMessage
from app.domains.books.base_workflow import BookWorkflow
from app.domains.books.external import BookRetrievalOutput
from clients import OpenAIParserRequest
from db.schema import BookMetadataFilter
from db.stores import DeferredBookQuery

from .schemas import FilterRetrievalArgs
from .external import FilterRetrievalInput, FilterRetrievalOutput

from common.prompts import basic_fill_schema_prompt


def build_arg_parser_request(query: str) -> OpenAIParserRequest:
    """Ask the LLM to fill `FilterRetrievalArgs` in from the goal text."""
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
        tool_models=[FilterRetrievalArgs],
        max_completion_tokens=2000,
    )


def anchor_queries(anchors: list[BookRetrievalOutput]) -> list[DeferredBookQuery]:
    """The queries this node can narrow, out of what its dependencies produced.

    **No registered node lands in the dropped branch since 2026-08-24.** It
    used to catch the similarity node, which handed on chosen rows and no
    query, on the reasoning that narrowing a ranked choice throws the ranking
    away. That reasoning was about *rows*: a scored `DeferredBookQuery` narrows
    fine, because `BookStore.filter_query` carries the `score` column through
    and `materialize_stmt` orders by it — so a bound on a similarity pool keeps
    cosine order end to end. The similarity node hands on such a query now.

    The guard stays because it is the honest reading of an optional field, and
    a goal left with nothing to narrow still says so in `run`.

    One thing a caller must know: a similarity pool is **truncated** to the
    nearest 250, so narrowing it means "of the 250 nearest, N pass" rather than
    "N in the catalog". Pooling one with another retrieval through `compose`
    compounds that — the LIMIT applies before the union, and `score` is dropped
    after — and nothing raises. See `DeferredBookQuery`.
    """
    return [anchor.query for anchor in anchors if anchor.query is not None]


def range_phrase(
    low: float | None,
    high: float | None,
    only_low: str,
    only_high: str,
    both: str,
    fmt: Callable[[Any], str] = str,
) -> str | None:
    """One bounded dimension as words, or None when it was left unbounded.

    Every numeric bound on `BookMetadataFilter` comes in a min/max pair with
    the same three cases, so the phrasing is a template per case rather than a
    branch per field — the four call sites below read as the four sentences
    the user will see.
    """
    if low is not None and high is not None:
        return both.format(low=fmt(low), high=fmt(high))
    if low is not None:
        return only_low.format(low=fmt(low))
    if high is not None:
        return only_high.format(high=fmt(high))
    return None


def describe_bounds(filters: BookMetadataFilter) -> str:
    """The bounds as the user-facing line, e.g. `300 pages or more, published
    between 2020 and 2022, not for children`.

    Only what the parse actually set — every other field is None, and an
    all-None filter is a no-op `BookStore.filter_query` refuses outright. The
    words are the point: this string is read twice by the user (the loading
    message and the count line) and never by anything else, so it says what the
    bounds mean rather than which fields carry them. Both ends are inclusive,
    which is why every phrase is "or more"/"or fewer" rather than "over"/"under".
    """
    parts = [
        range_phrase(
            filters.min_pages,
            filters.max_pages,
            "{low} pages or more",
            "{high} pages or fewer",
            "between {low} and {high} pages",
        ),
        range_phrase(
            filters.min_year,
            filters.max_year,
            "published in {low} or later",
            "published in {high} or earlier",
            "published between {low} and {high}",
        ),
        range_phrase(
            filters.min_rating,
            filters.max_rating,
            "rated {low} or higher",
            "rated {high} or lower",
            "rated between {low} and {high}",
            fmt=lambda value: f"{value:.1f}",
        ),
        range_phrase(
            filters.min_ratings_count,
            filters.max_ratings_count,
            "with at least {low} ratings",
            "with at most {high} ratings",
            "with between {low} and {high} ratings",
            fmt=lambda value: f"{value:,}",
        ),
    ]
    if filters.is_children is not None:
        parts.append("for children" if filters.is_children else "not for children")

    return ", ".join(part for part in parts if part)


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
                "Nothing to narrow: no anchor carries a query. Every registered "
                "retrieval hands one on, so this is a malformed upstream output "
                "rather than a plan this node can be asked to fix"
            )

        # 2. parse the goal text into this node's own schema
        parsed_args: FilterRetrievalArgs = await self.run_llm_args_parse(
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

        await self.sse_stream.send_chars(f"- {total} books left after: {bounds}")

        # 4. Cards for the section, streamed and let go — what travels
        # downstream is the narrowed query on `self.result`. Skipped entirely
        # when the bounds left nothing.
        if total:
            preview = await self.fetch_books(deferred)
            await self.stream_books(preview.unwrap())

        # 5. last: ok is read off the output
        self.finalize_result()

    def finalize_result(self):
        # ok means "the bounds were parsed and applied", not "something
        # survived them" — an empty result is an answer this node reports.
        ok = self.result.args is not None and self.result.query is not None
        return super().finalize_result(ok=ok)
