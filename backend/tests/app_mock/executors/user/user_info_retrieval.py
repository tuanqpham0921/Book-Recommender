import logging

from app.domains.users.schemas.request_schemas import DeveloperInfoRequest, UserInfoRequest
from app.orchestration.request_context import RequestContext

logger = logging.getLogger(__name__)


class UserInfoExecutor:
    async def __call__(
        self,
        task: UserInfoRequest,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting your account info...")
        await request_context.sse_stream.send_chars(
            "I have found some information about your account that you might find useful."
        )
        return "Mock result: user info"


class DeveloperInfoExecutor:
    async def __call__(
        self,
        task: DeveloperInfoRequest,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> str:
        await request_context.sse_stream.send_ui_loading("Getting developer info...")
        await request_context.sse_stream.send_chars(
            "I have found some information about the developer that you might find useful."
        )
        return "Mock result: developer info"
