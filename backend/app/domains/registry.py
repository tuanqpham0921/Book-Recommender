import inspect
from enum import Enum
from typing import Annotated, Union

from pydantic import Field

from app.domains.books.schemas.request_schemas import (
    CompareStrategy,
    FindByISBN13Retrieval,
    FindByTitleRetrieval,
    FindByTraitsRetrieval,
    RecommendationStrategy,
)
from app.domains.books.schemas.extended_request_schemas import (
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
from app.domains.project.schemas.request_schemas import (
    FeedbackRequest,
    ProjectInfoRequest,
)
from app.domains.node_types import NodeTypeEnum
from app.domains.users.schemas.request_schemas import (
    DeveloperInfoRequest,
    UserInfoRequest,
)

# -------------------------------------------------------------------
# BOOK DOMAIN
BOOK_RETRIEVAL_CLASSES = (
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByTraitsRetrieval,
    FindByAuthorRetrieval,
    FindSeriesRetrieval,
    AuthorInfoRetrieval,
    NewReleasesRetrieval,
    PopularBooksRetrieval,
    RandomBookRetrieval,
)
BOOK_ANALYZE_CLASSES = (
    CompareStrategy,
    RecommendationStrategy,
    SummarizeStrategy,
    ThemesStrategy,
    ReadingOrderStrategy,
    ReadingLevelStrategy,
    ReadingTimeStrategy,
    ReadingPlanStrategy,
)
BOOK_LIBRARY_CLASSES = (
    SaveToReadingListAction,
    ViewReadingListRetrieval,
    RemoveFromReadingListAction,
    MarkBookAsReadAction,
    RateBookAction,
    ReadingStatsRetrieval,
)
BOOK_REQUEST_CLASSES = (
    BOOK_RETRIEVAL_CLASSES + BOOK_ANALYZE_CLASSES + BOOK_LIBRARY_CLASSES
)

# -------------------------------------------------------------------
# PROJECT DOMAIN
PROJECT_RETRIEVAL_CLASSES = (
    ProjectInfoRequest,
)
PROJECT_ACTION_CLASSES = (
    FeedbackRequest,
)
PROJECT_REQUEST_CLASSES = PROJECT_RETRIEVAL_CLASSES + PROJECT_ACTION_CLASSES

# -------------------------------------------------------------------
# USER DOMAIN
USER_RETRIEVAL_CLASSES = (
    UserInfoRequest,
    DeveloperInfoRequest,
)

USER_REQUEST_CLASSES = USER_RETRIEVAL_CLASSES
# -------------------------------------------------------------------
# All request schema classes — a new class only needs to be added to its
# domain tier tuple above; the union, node_type lookup, and catalog below
# are all derived from these.

RETRIEVAL_CLASSES = BOOK_RETRIEVAL_CLASSES + USER_RETRIEVAL_CLASSES + PROJECT_RETRIEVAL_CLASSES
ANALYZE_CLASSES = BOOK_ANALYZE_CLASSES
LIBRARY_CLASSES = BOOK_LIBRARY_CLASSES
ACTION_CLASSES = PROJECT_ACTION_CLASSES

REQUEST_CLASSES = RETRIEVAL_CLASSES + ANALYZE_CLASSES + LIBRARY_CLASSES + ACTION_CLASSES

AnyStrategyRequest = Annotated[
    Union[*REQUEST_CLASSES],
    Field(discriminator="node_type"),
]


def _node_type_value(cls: type) -> str:
    """The node_type Literal default every request class declares."""
    return cls.model_fields["node_type"].default.value


NODE_TYPE_TO_CLS: dict[str, type] = {
    _node_type_value(cls): cls for cls in REQUEST_CLASSES
}
assert len(NODE_TYPE_TO_CLS) == len(REQUEST_CLASSES), (
    "Duplicate node_type across request classes — every class needs a unique "
    "node_type Literal default"
)


def get_request_class(node_type: NodeTypeEnum | str) -> type:
    # isinstance instead of hasattr: same runtime behavior, narrows the type
    key = node_type.value if isinstance(node_type, Enum) else node_type
    return NODE_TYPE_TO_CLS[key]


def class_docstring(cls: type) -> str:
    docs = inspect.getdoc(cls)
    if not docs:
        return "No description"
    return docs.strip()


def format_node_type_catalog() -> str:
    """Build a catalog of supported capabilities grouped by tier."""

    def lines_for(label: str, classes: tuple[type, ...]) -> list[str]:
        section = [f"{label}:"]
        for cls in classes:
            section.append(f"  - {_node_type_value(cls)}: {class_docstring(cls)}")
        return section

    catalog = [
        "Supported capabilities (only these may become system_goals):",
        *lines_for("Retrieval — lookup or fetch data", RETRIEVAL_CLASSES),
        "",
        *lines_for("Analyze — interpret, compare, or recommend using retrieved data", ANALYZE_CLASSES),
        "",
        *lines_for("Library — read or update the user's personal shelf", LIBRARY_CLASSES),
    ]

    listed = set(RETRIEVAL_CLASSES) | set(ANALYZE_CLASSES) | set(LIBRARY_CLASSES)
    extra = [cls for cls in REQUEST_CLASSES if cls not in listed]
    if extra:
        catalog.extend(["", *lines_for("Other supported actions", tuple(dict.fromkeys(extra)))])

    return "\n".join(catalog)


def main() -> None:
    print(format_node_type_catalog())


if __name__ == "__main__":
    main()
