import random
from typing import Any

from app.domains.books.schemas import RandomBookRetrieval
from app.domains.books.schemas.output_schemas import BookSummary, RandomBookOutput
from ..base import MockRetrievalExecutorWorkflow
from ...utils.mock_books import MOCK_BOOKS


class RandomBookExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Picking a book at random..."

    def select_books(
        self, task: RandomBookRetrieval, dependent_results: dict
    ) -> list[dict]:
        # The mock ignores task.filters — the real executor applies them in the
        # query so the pick is drawn from inside the bounds, not filtered after.
        return [random.choice(MOCK_BOOKS)]

    def build_data(
        self, task: RandomBookRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        output = RandomBookOutput(
            book=BookSummary.model_validate(books[0]) if books else None,
        )
        return output.model_dump()
