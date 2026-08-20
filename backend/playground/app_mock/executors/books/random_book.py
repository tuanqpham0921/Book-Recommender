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
        # query so the picks are drawn from inside the bounds, not filtered
        # after. sample() caps at the corpus size, so a limit larger than the
        # catalog returns everything rather than raising.
        return random.sample(MOCK_BOOKS, min(task.limit, len(MOCK_BOOKS)))

    def build_data(
        self, task: RandomBookRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        books = self.select_books(task, dependent_results)
        output = RandomBookOutput(
            books=[BookSummary.model_validate(b) for b in books],
        )
        return output.model_dump()
