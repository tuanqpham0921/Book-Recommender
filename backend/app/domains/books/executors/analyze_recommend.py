from typing import Any

from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow
from ..schemas.output_schemas import RecommendationOutput
from app.common.messages import AssistantMessage, APIMessage, ToolMessage, UserMessage
from clients.base import BaseLLMClient

class RecommendBooksExecutor(AppBaseWorkflow[RecommendationOutput]):
    ui_loading_message = "Finding similar books..."

    async def run(self, dependent_results):
        # 0. send a UI loading message
        # 1. with dependent_results, you can check if you have everything you need
        #    * for later version, you can call the planner to best effort retrieve
        # 2. call the args parser here
        # 3. (?) update the ui somehow (maybe the args parser can come-up with something)
        # 4. Same thing here, get build the CTE, get the closest books
        # 5. post-process the query and populate the output class
        # this returns actual books
        ...