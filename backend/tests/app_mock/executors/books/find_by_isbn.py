from typing import Any

from app.domains.books.schemas import FindByISBN13Retrieval
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_isbn13


class FindByISBN13Executor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Book By ISBN13..."

    def select_books(
        self, task: FindByISBN13Retrieval, dependent_results: dict
    ) -> list[dict]:
        return [find_by_isbn13(task.isbn13)]

    def build_data(
        self, task: FindByISBN13Retrieval, dependent_results: dict
    ) -> dict[str, Any]:
        book = self.select_books(task, dependent_results)[0]
        return {"isbn13": task.isbn13, "title": book["title"]}
