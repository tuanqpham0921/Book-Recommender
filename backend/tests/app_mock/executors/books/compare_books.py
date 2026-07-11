import logging

from app.domains.books.schemas import CompareStrategy
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class CompareBooksExecutor:
    async def __call__(
        self,
        task: CompareStrategy,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Comparing books...")
        await request_context.sse_stream.send_chars(
            "Here's how those books compare to each other."
        )
        return "Mock result: compared books"
