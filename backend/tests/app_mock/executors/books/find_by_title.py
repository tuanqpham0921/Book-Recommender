from typing import Any

from app.domains.books.schemas import FindByTitleRetrieval
from ..base import MockRetrievalExecutorWorkflow


class FindByTitleExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Book By Title..."

    def build_data(
        self, task: FindByTitleRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        return {
            "title": task.title,
            "authors": task.authors or ["Unknown Author"],
            "isbn13": "9780000000000",
        }
