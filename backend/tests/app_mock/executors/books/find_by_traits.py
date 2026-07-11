import logging

from app.domains.books.schemas import FindByTraitsRetrieval
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class FindByTraitsExecutor:
    async def __call__(
        self,
        task: FindByTraitsRetrieval,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting Books By Traits...")
        await request_context.sse_stream.send_chars(
            "I found some books that match what you're looking for."
        )
        return "Mock result: found books matching traits search"
