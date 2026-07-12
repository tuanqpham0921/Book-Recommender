from app.domains.books.schemas import (
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByTraitsRetrieval,
    CompareStrategy,
    RecommendationStrategy,
)
from app.domains.project.schemas import ProjectInfoRequest
from app.domains.users.schemas.request_schemas import DeveloperInfoRequest, UserInfoRequest

from .books import (
    FindByTitleExecutor,
    FindByISBN13Executor,
    FindByTraitsExecutor,
    CompareBooksExecutor,
    RecommendBooksExecutor,
)
from .project import ProjectInfoExecutor
from .user import UserInfoExecutor, DeveloperInfoExecutor

MOCK_EXECUTORS_CLS_MAPPING = {
    FindByTitleRetrieval: FindByTitleExecutor,
    FindByISBN13Retrieval: FindByISBN13Executor,
    FindByTraitsRetrieval: FindByTraitsExecutor,
    CompareStrategy: CompareBooksExecutor,
    RecommendationStrategy: RecommendBooksExecutor,
    ProjectInfoRequest: ProjectInfoExecutor,
    UserInfoRequest: UserInfoExecutor,
    DeveloperInfoRequest: DeveloperInfoExecutor,
}
