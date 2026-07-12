from typing import Any

from app.domains.books.schemas import FindByTraitsRetrieval
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_traits


class FindByTraitsExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Books By Traits..."

    def select_books(
        self, task: FindByTraitsRetrieval, dependent_results: dict
    ) -> list[dict]:
        return find_by_traits()

    def build_data(
        self, task: FindByTraitsRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        return {
            "search_criteria": task.search_criteria,
            "isbn13s": [b["isbn13"] for b in books],
        }
