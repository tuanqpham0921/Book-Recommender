from app.domains.books.schemas import FindByTitleRetrieval
from ..base import MockExecutorWorkflow


class FindByTitleExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting Book By Title..."

    def build_reply(self, task: FindByTitleRetrieval, dependent_results: dict) -> str:
        return f'I found a book matching the title "{task.title}".'
