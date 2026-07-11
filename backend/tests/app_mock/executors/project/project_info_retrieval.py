from app.domains.project.schemas import ProjectInfoRequest
from ..base import MockExecutorWorkflow


class ProjectInfoExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting project info..."

    def build_reply(self, task: ProjectInfoRequest, dependent_results: dict) -> str:
        return "I have found some information about the project that you might find useful."
