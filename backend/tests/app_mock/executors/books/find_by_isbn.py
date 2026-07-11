from typing import Any

from app.domains.books.schemas import FindByISBN13Retrieval
from ..base import MockRetrievalExecutorWorkflow


class FindByISBN13Executor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Book By ISBN13..."

    def build_data(
        self, task: FindByISBN13Retrieval, dependent_results: dict
    ) -> dict[str, Any]:
        return {
            "title": "Mock Book",
            "isbn13": task.isbn13,
        }
