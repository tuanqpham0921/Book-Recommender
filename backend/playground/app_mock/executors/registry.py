from app.domains.books.schemas import (
    FindByTitleRetrieval,
    RecommendationStrategy,
)

# CompareBooksExecutor is parked alongside CompareStrategy (Analyze_Compare) —
# see app/domains/books/registry.py. Its file/class still exist, just not
# imported or wired into the active mapping below.
from .books import (
    FindByTitleExecutor,
    RecommendBooksExecutor,
)

MOCK_EXECUTORS_CLS_MAPPING = {
    FindByTitleRetrieval: FindByTitleExecutor,
    RecommendationStrategy: RecommendBooksExecutor,
}
