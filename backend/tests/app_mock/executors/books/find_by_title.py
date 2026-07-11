import logging

from app.domains.books.schemas import FindByTitleRetrieval
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class FindByTitleExecutor:
    async def __call__(
        self,
        task: FindByTitleRetrieval,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting Book By Title...")
        await request_context.sse_stream.send_chars(
            f"I found a book matching the title \"{task.title}\"."
        )
        return f"Mock result: found book for title '{task.title}'"
