from app.domains.users.schemas.request_schemas import DeveloperInfoRequest, UserInfoRequest
from ..base import MockExecutorWorkflow


class UserInfoExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting your account info..."

    def build_reply(self, task: UserInfoRequest, dependent_results: dict) -> str:
        return "I have found some information about your account that you might find useful."


class DeveloperInfoExecutor(MockExecutorWorkflow):
    ui_loading_message = "Getting developer info..."

    def build_reply(self, task: DeveloperInfoRequest, dependent_results: dict) -> str:
        return "I have found some information about the developer that you might find useful."
