import inspect
import logging
from enum import Enum
from typing import Annotated, Union

from pydantic import Field

logger = logging.getLogger(__name__)

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
from playground.app_mock.executors.registry import MOCK_EXECUTORS_CLS_MAPPING

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
AnyStrategyRequest = Annotated[
    Union[
        CompareStrategy,
        RecommendationStrategy,
        FindByTitleRetrieval,
        FindByISBN13Retrieval,
        FindByTraitsRetrieval,
        UserInfoRequest,
        DeveloperInfoRequest,
        FeedbackRequest,
        ProjectInfoRequest,
    ],
    Field(discriminator="node_type"),
]


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
    # isinstance instead of hasattr: same runtime behavior, narrows the type
    key = node_type.value if isinstance(node_type, Enum) else node_type
    return NODE_TYPE_TO_CLS[key]


def class_docstring(cls: type) -> str:
    docs = inspect.getdoc(cls)
    if not docs:
        return "No description"
    return docs.strip()


CATALOG_TIERS: dict[str, tuple[type, ...]] = {
    "Retrieval — lookup or fetch data": RETRIEVAL_CLASSES,
    "Analyze — interpret, compare, or recommend using retrieved data": ANALYZE_CLASSES,
}


def catalog_entries() -> dict[str, dict[str, str]]:
    """Structured capability catalog: tier label -> {node_type: description}.

    Every entry comes from NODE_TYPE_TO_CLS, so each node type appears exactly
    once with its registered name. Registered classes missing from every tier
    in CATALOG_TIERS fall into an "Other supported actions" section; a tier
    class that was never registered has no node_type name for the LLM to use,
    so it is skipped with a warning.
    """
    cls_to_node_type = {cls: name for name, cls in NODE_TYPE_TO_CLS.items()}
    entries: dict[str, dict[str, str]] = {}
    listed: set[type] = set()

    for label, classes in CATALOG_TIERS.items():
        section: dict[str, str] = {}
        for cls in classes:
            name = cls_to_node_type.get(cls)
            if name is None:
                logger.warning(
                    f"{cls.__name__} is in catalog tier {label!r} but not in "
                    "NODE_TYPE_TO_CLS — skipped from the capability catalog"
                )
                continue
            section[name] = class_docstring(cls)
            listed.add(cls)
        if section:
            entries[label] = section

    extra = {
        name: class_docstring(cls)
        for name, cls in NODE_TYPE_TO_CLS.items()
        if cls not in listed
    }
    if extra:
        entries["Other supported actions"] = extra

    return entries


def format_node_type_catalog() -> str:
    """Render catalog_entries() as the prompt block the planner LLM sees.

    Each capability is its name on one line with the (possibly multi-line)
    description indented under it, so long docstrings stay visually attached
    to their name instead of bleeding into the next entry.
    """
    lines = []
    for label, section in catalog_entries().items():
        lines += ["", f"## {label}", ""]
        for name, description in section.items():
            lines.append(name)
            lines += [
                f"  {doc_line}" if doc_line.strip() else ""
                for doc_line in description.splitlines()
            ]
            lines.append("")
    if not lines:
        raise  RuntimeError("Node type catalog is empty.")
    
    return "\n".join(lines).rstrip()


# -------------------------------------------------------------------
# EXECUTOR MAPPING

# NOTE: temporary — points at the mock executors under playground/app_mock
# until real domain executors are built, then this should map to those instead.
EXECUTORS_CLS_MAPPING = MOCK_EXECUTORS_CLS_MAPPING



def main() -> None:
    print(format_node_type_catalog())


# -------------------------------------------------------------------
# PLAYGROUND EXTENSION — comment out this whole block to run with only the
# app-registered node types above; nothing else in this file needs to change.
# Folds the scalability-testing schemas from
# playground/app_mock/extended_registry.py into the live planner registry.
# Must run before the __main__ guard below, so `python -m app.registry`
# reflects the same registry state everything else sees.
from playground.app_mock.extended_registry import (
    ExtendedANALYZE_CLASSES,
    ExtendedLIBRARY_CLASSES,
    ExtendedNODE_TYPE_TO_CLS,
    ExtendedRETRIEVAL_CLASSES,
)

RETRIEVAL_CLASSES = RETRIEVAL_CLASSES + ExtendedRETRIEVAL_CLASSES
ANALYZE_CLASSES = ANALYZE_CLASSES + ExtendedANALYZE_CLASSES
# ExtendedLIBRARY_CLASSES is neither retrieval nor analyze (read/write actions
# on the user's shelf) — folded into REQUEST_CLASSES only, so it still counts
# as a request class without joining either tier's class list
REQUEST_CLASSES = RETRIEVAL_CLASSES + ANALYZE_CLASSES + ExtendedLIBRARY_CLASSES

NODE_TYPE_TO_CLS.update(ExtendedNODE_TYPE_TO_CLS)
CATALOG_TIERS["Retrieval — lookup or fetch data"] = RETRIEVAL_CLASSES
CATALOG_TIERS["Analyze — interpret, compare, or recommend using retrieved data"] = ANALYZE_CLASSES


if __name__ == "__main__":
    main()
