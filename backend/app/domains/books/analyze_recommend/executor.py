from typing import Any

from app.domains.node_executor import NodeExecutor
from app.orchestration.request_context import RequestContext
from .schemas import RecommendationOutput, RecommendationStrategy


class RecommendBooksExecutor(NodeExecutor[RecommendationOutput]):
    ui_loading_message = "Finding similar books..."

    async def run(
        self,
        task: RecommendationStrategy,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        # 0. send a UI loading message
        # 1. with dependent_results, you can check if you have everything you need
        #    * for later version, you can call the planner to best effort retrieve
        # 2. call the args parser here
        # 3. (?) update the ui somehow (maybe the args parser can come-up with something)
        # 4. Same thing here, get build the CTE, get the closest books
        # 5. post-process the query and populate the output class
        # this returns actual books
        raise NotImplementedError(
            "RecommendBooksExecutor is a stub — app/registry.py still routes "
            "this node to the mock executor in playground/app_mock."
        )
