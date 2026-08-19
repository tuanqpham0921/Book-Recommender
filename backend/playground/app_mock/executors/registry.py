from app.domains.books.analyze_recommend import RecommendationStrategy
from app.domains.books.find_by_title import FindByTitleRetrieval

# CompareBooksExecutor is parked alongside CompareStrategy (Analyze_Compare) —
# see app/domains/books/guide.py. Its file/class still exist, just not
# imported or wired into the active mapping below.
from .books import (
    FindByTitleExecutor,
    RecommendBooksExecutor,
)

MOCK_EXECUTORS_CLS_MAPPING = {
    FindByTitleRetrieval: FindByTitleExecutor,
    RecommendationStrategy: RecommendBooksExecutor,
}
