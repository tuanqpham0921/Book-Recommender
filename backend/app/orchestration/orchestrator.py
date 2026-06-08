import json
import logging
import asyncio
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import ToolMessage
from .planner.schemas import TaskPlan
from .planner.executors import run_initial_step, run_analyze_classification, run_create_task_plan
from app.domains.books.strategies import BOOK_STRAT_REGISTRY

from common.operation import OperationResult, task
from common.utils import save_file
logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine for processing user queries through AI pipelines."""

    def __init__(self):
        """Initialize the orchestrator."""
        # Here you can initialize any resources that are needed for the orchestrator
        # like saving logs to a file or a database
        # update user info after each request
        # this is one App level resource that can be used by all requests
        # so it will hold references that are needed for the resources managed by the orchestrator
        # self.log_session_factory = None
        pass
    
    

    async def run_tasks(
        self, 
        node_ids, 
        task_planner_: TaskPlan, 
        request_context: RequestContext
    ):
        """Execute tasks in the planned order with dependency resolution."""

        depends_map = {cur.id: cur.depends_on for cur in task_planner_.accepted}
        results = {}

        for tid in task_planner_.execution_order:
            task = node_ids[tid]
            deps = {d: results[d] for d in depends_map[tid]}

            node_type = task.node_type

            # Create strategy instance and call it with proper arguments
            strategy_class = BOOK_STRAT_REGISTRY[node_type]
            strategy_instance = strategy_class()

            # Pass the task data and context to the strategy
            result = await strategy_instance(
                task=task, dependent_results=deps, request_context=request_context
            )

            results[tid] = result

        return results
    
    @task
    async def _run_conversation_step(
        self,
        request_context: RequestContext,
        sse_stream: SSEStream,
    ) -> OperationResult:
        """Execute the complete conversation pipeline from parsing to task execution."""
        steps = []
        
        initial_parse = await run_initial_step(request_context, sse_stream)
        steps.append(initial_parse)
        if not initial_parse.ok:
            # should just be out of scope or no domain identified
            return OperationResult(
                name="initial_parse",
                ok=True,
                message="User query classified as out-of-scope or no domain identified. Ending pipeline.",
                details={"initial_parse": initial_parse}
            )
        
        request_context.pipeline_context["in_domain_message"] = (
            initial_parse.result.model_dump_json(
                include={"user_query_domain", "continue_pipeline", "reasoning"}
            )
        )

        await sse_stream.send_ui_loading("Classifying User Request...")

        classified_strategy_ = await run_analyze_classification(
            request_context=request_context,
            initial_parse=initial_parse.result,
        )

        node_ids = classified_strategy_.get_accepted_node_ids()

        # ----------------------------------------------------------
        await sse_stream.send_ui_loading("Planning The Tasks...")
        task_planner_ = await run_create_task_plan(
            request_context=request_context,
            initial_parse=initial_parse.result,
            node_ids=node_ids,
        )

        if task_planner_:
            # task_planner_.export()
            mermaid_diagram = task_planner_.get_accepted_diagram(node_ids)
            await sse_stream.send_chars("__My Plan for Your Request__")
            await sse_stream.send_mermaid(mermaid_diagram)
            await sse_stream.send_chars(
                "_Note:_ This flow shows how your query will run.\n"
            )
            await sse_stream.send_chars(
                "Soon, you’ll be able to edit or customize the plan before execution for full transparency!"
            )
            await sse_stream.send_divider()
        else:
            await sse_stream.send_error("Unable to generate a Task Planner")

        # ----------------------------------------------------------
        await sse_stream.send_ui_loading("Executing the tasks...")

        result = await self.run_tasks(
            node_ids,
            task_planner_,
            request_context=request_context,
        )
        
        return OperationResult(
            name="run_tasks",
            ok=True,
            steps=steps,
            message="Tasks executed successfully.",
            details={"tasks": result}
        )

        

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""
        sse_stream = request_context.sse_stream
        try:
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            result = await asyncio.wait_for(
                self._run_conversation_step(request_context, sse_stream),
                timeout=300.0,
            )

            # Normal completion
            await sse_stream.send("complete", {"status": "completed"})
            logger.info("✅ Orchestration completed successfully")

        #TODO: add Dev vs Prod handling
        except asyncio.TimeoutError:
            msg = "Uhh... request timed out (5 mins) while processing your query."
            logger.info(msg)
            await sse_stream.send_error(msg)

        except asyncio.CancelledError:
            # Raised if server reloads or client disconnects mid-stream
            logger.info("🛑 Orchestration cancelled before shutdown or client abort.")
            await sse_stream.send_error(
                f"Oh no... orchestration server while processing your query."
            )

        except Exception as e:
            logger.exception(f"❌ Unhandled orchestrator error: {e}")
            # await sse_stream.send_error(f"Internal error: {str(e)}")
            await sse_stream.send_error(
                f"Hmm... something went wrong while processing your query."
            )

        finally:
            save_file(result, file_name=f"orchestration_result-dev")