from typing import Any

from app.domains.books.schemas import FindByGenreRetrieval
from app.domains.books.schemas.output_schemas import BookSummary, FindByGenreOutput
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import find_by_genre


class FindByGenreExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Books By Genre..."

    def select_books(
        self, task: FindByGenreRetrieval, dependent_results: dict
    ) -> list[dict]:
        return find_by_genre(task.genre)

    def build_data(
        self, task: FindByGenreRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        output = FindByGenreOutput(
            genre=task.genre,
            books=[BookSummary.model_validate(b) for b in books],
        )
        return output.model_dump()
