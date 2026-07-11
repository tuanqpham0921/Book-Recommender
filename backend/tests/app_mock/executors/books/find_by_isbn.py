from app.domains.books.schemas import FindByISBN13Retrieval
from ..base import MockExecutorWorkflow


class FindByISBN13Executor(MockExecutorWorkflow):
    ui_loading_message = "Getting Book By ISBN13..."

    def build_reply(self, task: FindByISBN13Retrieval, dependent_results: dict) -> str:
        return f"I found a book matching ISBN13 {task.isbn13}."
