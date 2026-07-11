from app.domains.books.schemas import CompareStrategy
from ..base import MockExecutorWorkflow


class CompareBooksExecutor(MockExecutorWorkflow):
    ui_loading_message = "Comparing books..."

    def build_reply(self, task: CompareStrategy, dependent_results: dict) -> str:
        return "Here's how those books compare to each other."
