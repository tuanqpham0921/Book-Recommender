from typing import Any

from app.domains.books.schemas import FindByTraitsRetrieval
from ..base import MockRetrievalExecutorWorkflow


class FindByTraitsExecutor(MockRetrievalExecutorWorkflow):
    ui_loading_message = "Getting Books By Traits..."

    def build_data(
        self, task: FindByTraitsRetrieval, dependent_results: dict
    ) -> dict[str, Any]:
        return {
            "search_criteria": task.search_criteria,
            "books": [{"title": "Mock Book 1"}, {"title": "Mock Book 2"}],
        }
