from app.domains.project.schemas import FeedbackRequest
from ..base import MockExecutorWorkflow


class FeedbackExecutor(MockExecutorWorkflow):
    ui_loading_message = "Recording your feedback..."

    def build_reply(self, task: FeedbackRequest, dependent_results: dict) -> str:
        contact_note = (
            f" I'll follow up at {task.contact_info} if there's anything to share."
            if task.contact_info
            else " Feel free to leave contact info next time if you'd like a reply."
        )
        return (
            "## Thanks for the feedback\n\n"
            f"> {task.feedback}\n\n"
            "I've noted this down." + contact_note
        )
