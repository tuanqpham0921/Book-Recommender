"""Book-domain registry: class tuples and node_type -> class lookup for this
domain only. app/registry.py composes this with the other domains' registries
plus the catalog and executor mapping — see that module for the full picture.
"""

from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas.request_schemas import (
    FindByISBN13Retrieval,
    FindByAuthorRetrieval,
    FindByGenreRetrieval,
    FindByTitleRetrieval,
    RecommendationStrategy,
)

# CompareStrategy (Analyze_Compare) is intentionally parked: the class still
# lives in schemas/request_schemas.py and is directly importable, but it's
# out of BOOK_ANALYZE_CLASSES / BOOK_NODE_TYPE_TO_CLS, so it's absent from
# the catalog and the planner refuses any goal targeting it (parse_intent.py
# gates on NODE_TYPE_TO_CLS membership). See docs/design/node-taxonomy-v1.md.
BOOK_RETRIEVAL_CLASSES = (
    FindByTitleRetrieval,
    FindByISBN13Retrieval,
    FindByAuthorRetrieval,
    FindByGenreRetrieval,
)
BOOK_ANALYZE_CLASSES = (
    RecommendationStrategy,
)
BOOK_REQUEST_CLASSES = BOOK_RETRIEVAL_CLASSES + BOOK_ANALYZE_CLASSES

# Manual node_type -> class lookup — add new mappings here
BOOK_NODE_TYPE_TO_CLS: dict[str, type] = {
    BookNodeTypeEnum.FIND_TITLE.value: FindByTitleRetrieval,
    BookNodeTypeEnum.FIND_ISBN13.value: FindByISBN13Retrieval,
    BookNodeTypeEnum.FIND_AUTHOR.value: FindByAuthorRetrieval,
    BookNodeTypeEnum.FIND_GENRE.value: FindByGenreRetrieval,
    BookNodeTypeEnum.RECOMMENDATION.value: RecommendationStrategy,
}
