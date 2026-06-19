from typing import Annotated, Union

from pydantic import Field

from app.domains.books.schemas.request_schemas import (
    CompareStrategy,
    FindByISBN13Retrieval,
    FindByTitleRetrieval,
    FindByTraitsRetrieval,
    RecommendationStrategy,
)
from app.domains.books.types import NodeTypeEnum as BookNodeTypeEnum
from app.domains.project.schemas.request_schemas import (
    FeedbackRequest,
    ProjectInfoRequest,
)
from app.domains.project.types import NodeTypeEnum as ProjectNodeTypeEnum
from app.domains.types import NodeTypeEnum
from app.domains.users.schemas.request_schemas import (
    DeveloperInfoRequest,
    UserInfoRequest,
)
from app.domains.users.types import NodeTypeEnum as UserNodeTypeEnum

# All request schema classes — add new ones here
REQUEST_CLASSES = (
    CompareStrategy,
    RecommendationStrategy,
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByTraitsRetrieval,
    UserInfoRequest,
    DeveloperInfoRequest,
    ProjectInfoRequest,
    FeedbackRequest,
)

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
    ProjectNodeTypeEnum.FEEDBACK.value: FeedbackRequest,
}


def get_request_class(node_type: NodeTypeEnum | str) -> type:
    key = node_type.value if hasattr(node_type, "value") else node_type
    return NODE_TYPE_TO_CLS[key]


# Discriminated union for OpenAI tool schemas (strategy classification)
AllRequests = Annotated[
    Union[REQUEST_CLASSES],
    Field(discriminator="node_type"),
]

