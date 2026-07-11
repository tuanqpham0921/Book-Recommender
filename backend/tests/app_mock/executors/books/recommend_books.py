from app.domains.books.schemas import RecommendationStrategy
from ..base import MockExecutorWorkflow


class RecommendBooksExecutor(MockExecutorWorkflow):
    ui_loading_message = "Finding book recommendations..."

    def build_reply(self, task: RecommendationStrategy, dependent_results: dict) -> str:
        return "I have found some books that you might like based on your preferences."
