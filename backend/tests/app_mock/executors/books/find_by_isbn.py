import logging

from app.domains.books.schemas import FindByISBN13Retrieval
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class FindByISBN13Executor:
    async def __call__(
        self,
        task: FindByISBN13Retrieval,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting Book By ISBN13...")
        await request_context.sse_stream.send_chars(
            f"I found a book matching ISBN13 {task.isbn13}."
        )
        return f"Mock result: found book for isbn13 '{task.isbn13}'"
