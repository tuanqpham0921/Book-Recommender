from typing import Any

from app.domains.books.schemas import FindByCoAuthorsRetrieval
from app.domains.books.schemas.output_schemas import BookSummary, FindByCoAuthorsOutput
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_coauthors


class FindByCoAuthorsExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Looking For Their Collaborations..."

    def select_books(
        self, task: FindByCoAuthorsRetrieval, dependent_results: dict
    ) -> list[dict]:
        return find_by_coauthors(task.authors)

    def build_data(
        self, task: FindByCoAuthorsRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        output = FindByCoAuthorsOutput(
            authors=task.authors,
            books=[BookSummary.model_validate(b) for b in books],
        )
        return output.model_dump()
