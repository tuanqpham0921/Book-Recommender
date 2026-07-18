from typing import Any

from app.domains.books.schemas import FindByAuthorRetrieval
from app.domains.books.schemas.output_schemas import BookSummary, FindByAuthorOutput
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_author


class FindByAuthorExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Books By Author..."

    def select_books(
        self, task: FindByAuthorRetrieval, dependent_results: dict
    ) -> list[dict]:
        return find_by_author(task.authors)

    def build_data(
        self, task: FindByAuthorRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        output = FindByAuthorOutput(
            authors=task.authors,
            books=[BookSummary.model_validate(b) for b in books],
        )
        return output.model_dump()
