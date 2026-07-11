import logging

from app.domains.project.schemas import ProjectInfoRequest
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class ProjectInfoExecutor:
    async def __call__(
        self,
        task: ProjectInfoRequest,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting project info...")
        await request_context.sse_stream.send_chars(
            "I have found some information about the project that you might find useful."
        )
        return "Mock result: project info"
