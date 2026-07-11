from typing import Any

from app.domains.books.schemas import FindByTitleRetrieval
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_title


class FindByTitleExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Book By Title..."

    def select_books(
        self, task: FindByTitleRetrieval, dependent_results: dict
    ) -> list[dict]:
        return find_by_title(task.title)

    def build_data(
        self, task: FindByTitleRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        return {"title": task.title, "isbn13s": [b["isbn13"] for b in books]}
