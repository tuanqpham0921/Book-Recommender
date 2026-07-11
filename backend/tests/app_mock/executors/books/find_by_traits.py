from app.domains.books.schemas import FindByTraitsRetrieval
from ..base import MockExecutorWorkflow


class FindByTraitsExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting Books By Traits..."

    def build_reply(self, task: FindByTraitsRetrieval, dependent_results: dict) -> str:
        return "I found some books that match what you're looking for."
