import inspect
from typing import Annotated, Union

from pydantic import Field

from app.domains.books.schemas.request_schemas import (
    CompareStrategy,
    FindByISBN13Retrieval,
    FindByTitleRetrieval,
    FindByTraitsRetrieval,
    RecommendationStrategy,
)
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.project.schemas.request_schemas import (
    FeedbackRequest,
    ProjectInfoRequest,
)
from app.domains.project.node_types import ProjectNodeTypeEnum
from app.domains.node_types import NodeTypeEnum
from app.domains.users.schemas.request_schemas import (
    DeveloperInfoRequest,
    UserInfoRequest,
)
from app.domains.users.node_types import UserNodeTypeEnum

# -------------------------------------------------------------------
# BOOK DOMAIN
BOOK_RETRIEVAL_CLASSES = (
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByTraitsRetrieval,
)
BOOK_ANALYZE_CLASSES = (
    CompareStrategy,
    RecommendationStrategy,
)
BOOK_REQUEST_CLASSES = BOOK_RETRIEVAL_CLASSES + BOOK_ANALYZE_CLASSES

# -------------------------------------------------------------------
# PROJECT DOMAIN
PROJECT_RETRIEVAL_CLASSES = (
    ProjectInfoRequest,
)

PROJECT_REQUEST_CLASSES = PROJECT_RETRIEVAL_CLASSES

# -------------------------------------------------------------------
# USER DOMAIN
USER_RETRIEVAL_CLASSES = (
    UserInfoRequest,
    DeveloperInfoRequest,
)

USER_REQUEST_CLASSES = USER_RETRIEVAL_CLASSES
# -------------------------------------------------------------------
# All request schema classes — add new ones here

RETRIEVAL_CLASSES = BOOK_RETRIEVAL_CLASSES + USER_RETRIEVAL_CLASSES + PROJECT_RETRIEVAL_CLASSES
ANALYZE_CLASSES = BOOK_ANALYZE_CLASSES

REQUEST_CLASSES = RETRIEVAL_CLASSES + ANALYZE_CLASSES

# Manual node_type → class lookup — add new mappings here
NODE_TYPE_TO_CLS: dict[str, type] = {
    BookNodeTypeEnum.COMPARE.value: CompareStrategy,
    BookNodeTypeEnum.RECOMMENDATION.value: RecommendationStrategy,
    BookNodeTypeEnum.FIND_TITLE.value: FindByTitleRetrieval,
    BookNodeTypeEnum.FIND_ISBN13.value: FindByISBN13Retrieval,
    BookNodeTypeEnum.FIND_TRAITS.value: FindByTraitsRetrieval,
    UserNodeTypeEnum.USER_INFO.value: UserInfoRequest,
    UserNodeTypeEnum.DEVELOPER_INFO.value: DeveloperInfoRequest,
    ProjectNodeTypeEnum.PROJECT_INFO.value: ProjectInfoRequest,
}


def get_request_class(node_type: NodeTypeEnum | str) -> type:
    key = node_type.value if hasattr(node_type, "value") else node_type
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
            for node_type, mapped_cls in NODE_TYPE_TO_CLS.items():
                if mapped_cls is cls:
                    section.append(f"  - {node_type}: {class_docstring(cls)}")
                    break
        return section

    catalog = [
        "Supported capabilities (only these may become system_goals):",
        *lines_for("Retrieval — lookup or fetch data", RETRIEVAL_CLASSES),
        "",
        *lines_for("Analyze — interpret, compare, or recommend using retrieved data", ANALYZE_CLASSES),
    ]

    listed =  set(ANALYZE_CLASSES)
    extra = [cls for cls in NODE_TYPE_TO_CLS.values() if cls not in listed]
    if extra:
        catalog.extend(["", *lines_for("Other supported actions", tuple(dict.fromkeys(extra)))])

    return "\n".join(catalog)


def main() -> None:
    print(format_node_type_catalog())


if __name__ == "__main__":
    main()