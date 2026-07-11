import logging

from app.domains.books.schemas import RecommendationStrategy
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class RecommendBooksExecutor:
    async def __call__(
        self,
        task: RecommendationStrategy,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Finding book recommendations...")
        await request_context.sse_stream.send_chars(
            "I have found some books that you might like based on your preferences."
        )
        return "Mock result: recommended books"
