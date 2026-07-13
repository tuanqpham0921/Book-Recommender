"""Registry for the scalability-testing schemas in extended_request_schemas.py.

Mirrors the shape of app/registry.py (domain class tuples, the combined
NODE_TYPE_TO_CLS lookup, the AnyStrategyRequest union) but kept entirely in
playground/ — nothing here is imported by app/ code, so it stays fully
detached from the live tool catalog.

To try these out against the real planner, combine this module's dicts/tuples
with the ones in app.registry at the call site (e.g. `{**NODE_TYPE_TO_CLS,
**ExtendedNODE_TYPE_TO_CLS}`) rather than mutating app.registry in place.
"""

from typing import Annotated, Union

from pydantic import Field

from playground.app_mock.extended_node_types import ExtendedBookNodeTypeEnum
from playground.app_mock.extended_request_schemas import (
    AuthorInfoRetrieval,
    FindByAuthorRetrieval,
    FindSeriesRetrieval,
    MarkBookAsReadAction,
    NewReleasesRetrieval,
    PopularBooksRetrieval,
    RandomBookRetrieval,
    RateBookAction,
    ReadingLevelStrategy,
    ReadingOrderStrategy,
    ReadingPlanStrategy,
    ReadingStatsRetrieval,
    ReadingTimeStrategy,
    RemoveFromReadingListAction,
    SaveToReadingListAction,
    SummarizeStrategy,
    ThemesStrategy,
    ViewReadingListRetrieval,
)

# -------------------------------------------------------------------
# BOOK DOMAIN (extended)
ExtendedBOOK_RETRIEVAL_CLASSES = (
    FindByAuthorRetrieval,
    FindSeriesRetrieval,
    AuthorInfoRetrieval,
    NewReleasesRetrieval,
    PopularBooksRetrieval,
    RandomBookRetrieval,
)
ExtendedBOOK_ANALYZE_CLASSES = (
    SummarizeStrategy,
    ThemesStrategy,
    ReadingOrderStrategy,
    ReadingLevelStrategy,
    ReadingTimeStrategy,
    ReadingPlanStrategy,
)
ExtendedBOOK_REQUEST_CLASSES = ExtendedBOOK_RETRIEVAL_CLASSES + ExtendedBOOK_ANALYZE_CLASSES

# -------------------------------------------------------------------
# LIBRARY DOMAIN (extended) — the user's personal shelf, reads and writes
ExtendedLIBRARY_CLASSES = (
    SaveToReadingListAction,
    ViewReadingListRetrieval,
    RemoveFromReadingListAction,
    MarkBookAsReadAction,
    RateBookAction,
    ReadingStatsRetrieval,
)
ExtendedLIBRARY_REQUEST_CLASSES = ExtendedLIBRARY_CLASSES

# -------------------------------------------------------------------
# All extended request schema classes — add new ones here

ExtendedRETRIEVAL_CLASSES = ExtendedBOOK_RETRIEVAL_CLASSES
ExtendedANALYZE_CLASSES = ExtendedBOOK_ANALYZE_CLASSES

ExtendedREQUEST_CLASSES = (
    ExtendedRETRIEVAL_CLASSES + ExtendedANALYZE_CLASSES + ExtendedLIBRARY_REQUEST_CLASSES
)
ExtendedAnyStrategyRequest = Annotated[
    Union[
        FindByAuthorRetrieval,
        FindSeriesRetrieval,
        AuthorInfoRetrieval,
        NewReleasesRetrieval,
        PopularBooksRetrieval,
        RandomBookRetrieval,
        SummarizeStrategy,
        ThemesStrategy,
        ReadingOrderStrategy,
        ReadingLevelStrategy,
        ReadingTimeStrategy,
        ReadingPlanStrategy,
        SaveToReadingListAction,
        ViewReadingListRetrieval,
        RemoveFromReadingListAction,
        MarkBookAsReadAction,
        RateBookAction,
        ReadingStatsRetrieval,
    ],
    Field(discriminator="node_type"),
]


# Manual node_type → class lookup — add new mappings here
ExtendedNODE_TYPE_TO_CLS: dict[str, type] = {
    ExtendedBookNodeTypeEnum.FIND_AUTHOR.value: FindByAuthorRetrieval,
    ExtendedBookNodeTypeEnum.FIND_SERIES.value: FindSeriesRetrieval,
    ExtendedBookNodeTypeEnum.AUTHOR_INFO.value: AuthorInfoRetrieval,
    ExtendedBookNodeTypeEnum.NEW_RELEASES.value: NewReleasesRetrieval,
    ExtendedBookNodeTypeEnum.POPULAR.value: PopularBooksRetrieval,
    ExtendedBookNodeTypeEnum.RANDOM.value: RandomBookRetrieval,
    ExtendedBookNodeTypeEnum.SUMMARIZE.value: SummarizeStrategy,
    ExtendedBookNodeTypeEnum.THEMES.value: ThemesStrategy,
    ExtendedBookNodeTypeEnum.READING_ORDER.value: ReadingOrderStrategy,
    ExtendedBookNodeTypeEnum.READING_LEVEL.value: ReadingLevelStrategy,
    ExtendedBookNodeTypeEnum.READING_TIME.value: ReadingTimeStrategy,
    ExtendedBookNodeTypeEnum.READING_PLAN.value: ReadingPlanStrategy,
    ExtendedBookNodeTypeEnum.READING_LIST_ADD.value: SaveToReadingListAction,
    ExtendedBookNodeTypeEnum.READING_LIST_VIEW.value: ViewReadingListRetrieval,
    ExtendedBookNodeTypeEnum.READING_LIST_REMOVE.value: RemoveFromReadingListAction,
    ExtendedBookNodeTypeEnum.MARK_AS_READ.value: MarkBookAsReadAction,
    ExtendedBookNodeTypeEnum.RATE_BOOK.value: RateBookAction,
    ExtendedBookNodeTypeEnum.READING_STATS.value: ReadingStatsRetrieval,
}


# -------------------------------------------------------------------
# CATALOG TIERS (extended) — merge into app.registry.CATALOG_TIERS at the
# call site to fold these into format_node_type_catalog()'s output, e.g.:
#   {**CATALOG_TIERS, **ExtendedCATALOG_TIERS}
ExtendedCATALOG_TIERS: dict[str, tuple[type, ...]] = {
    "Retrieval — lookup or fetch data": ExtendedRETRIEVAL_CLASSES,
    "Analyze — interpret, compare, or recommend using retrieved data": ExtendedANALYZE_CLASSES,
    "Library — the user's personal shelf (reads and writes)": ExtendedLIBRARY_CLASSES,
}
