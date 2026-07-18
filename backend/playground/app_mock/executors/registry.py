from app.domains.books.schemas import (
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByAuthorRetrieval,
    FindByGenreRetrieval,
    RecommendationStrategy,
)
from app.domains.project.schemas import FeedbackRequest, ProjectInfoRequest
from app.domains.users.schemas.request_schemas import DeveloperInfoRequest, UserInfoRequest

# CompareBooksExecutor is parked alongside CompareStrategy (Analyze_Compare) —
# see app/domains/books/registry.py. Its file/class still exist, just not
# imported or wired into the active mapping below.
from .books import (
    FindByTitleExecutor,
    FindByISBN13Executor,
    FindByAuthorExecutor,
    FindByGenreExecutor,
    RecommendBooksExecutor,
)
from .project import ProjectInfoExecutor, FeedbackExecutor
from .user import UserInfoExecutor, DeveloperInfoExecutor

MOCK_EXECUTORS_CLS_MAPPING = {
    FindByTitleRetrieval: FindByTitleExecutor,
    FindByISBN13Retrieval: FindByISBN13Executor,
    FindByAuthorRetrieval: FindByAuthorExecutor,
    FindByGenreRetrieval: FindByGenreExecutor,
    RecommendationStrategy: RecommendBooksExecutor,
    ProjectInfoRequest: ProjectInfoExecutor,
    FeedbackRequest: FeedbackExecutor,
    UserInfoRequest: UserInfoExecutor,
    DeveloperInfoRequest: DeveloperInfoExecutor,
}
