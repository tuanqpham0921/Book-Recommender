import json
import logging
import asyncio
import time

from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from app.common.messages import ToolMessage

from app.domains.planner.schemas import TaskPlan
from app.domains.planner.executors import run_initial_step, run_analyze_classification, run_create_task_plan
from app.domains.books.strategies import BOOK_STRAT_REGISTRY


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

    async def handle_tool_call(
        self, tool_calls, max_calls: int = 10, **extra_kwargs
    ) -> list[ToolMessage]:
        """Execute tool calls and return the results."""
        results = []
        for tool_call in tool_calls[:max_calls]:
            try:

                tool_name = tool_call.function.name
                tool_id = tool_call.id
                logger.info(f"🔧 Starting tool call: {tool_name} (id: {tool_id})")

                raw_args = json.loads(tool_call.function.arguments)
                tool_instance = tool_call.function.parsed_arguments

                start = time.monotonic()
                # logger.info(f"⚡ Executing {tool_name} with args: {raw_args}")
                logger.info(f"⚡ Executing {tool_name}")

                result = await tool_instance(**extra_kwargs)
                elapsed = round(time.monotonic() - start, 2)

                logger.info(f"✅ Tool {tool_name} completed successfully in {elapsed}s")

                results.append(
                    ToolMessage(
                        name=tool_call.function.name,
                        tool_call_id=tool_call.id,
                        content=result,
                        elapsed=elapsed,
                    )
                )
            except json.JSONDecodeError as e:
                logger.error(f"🛑 JSON parsing failed for tool {tool_name}: {e}")
                continue
            except Exception as e:
                logger.error(
                    f"🛑 Tool execution failed for {tool_name}: {e}", exc_info=True
                )
                continue

        return results

    async def run_tasks(
        self, node_ids, task_planner_: TaskPlan, sse_stream: SSEStream, request_context
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

    async def _run_conversation_step(
        self,
        request_context: RequestContext,
        sse_stream: SSEStream,
    ):
        """Execute the complete conversation pipeline from parsing to task execution."""
        try:
            initial_parse_result = await run_initial_step(
                request_context, sse_stream
            )
            if (
                not initial_parse_result.continue_pipeline
                or not initial_parse_result.user_query_domain
            ):
                logger.info(
                    "User query classified as out-of-scope or no domain identified. Ending pipeline."
                )
                return

            request_context.pipeline_context["in_domain_message"] = (
                initial_parse_result.model_dump_json(
                    include={"user_query_domain", "continue_pipeline", "reasoning"}
                )
            )

            await sse_stream.send_ui_loading("Classifying User Request...")

            classified_strategy_ = await run_analyze_classification(
                request_context=request_context,
                initial_parse_result=initial_parse_result,
            )

            node_ids = classified_strategy_.get_accepted_node_ids()

            # ----------------------------------------------------------
            await sse_stream.send_ui_loading("Planning The Tasks...")
            task_planner_ = await run_create_task_plan(
                request_context=request_context,
                initial_parse_result=initial_parse_result,
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
                sse_stream=sse_stream,
                request_context=request_context,
            )

        except Exception as e:
            logger.error(f"Error in conversation step: {str(e)}")
            raise
        finally:
            ...
            # request_context.export()
            # await request_context.persist_chat_messages()
            # await request_context.state_manager.export_snapshot(
            #     request_context.session_id
            # )

    async def run(self, request_context: RequestContext):
        """Run orchestration with SSE streaming."""
        sse_stream = request_context.sse_stream
        try:
            await sse_stream.send_ui_loading("Starting conversation...")

            # Core work
            await asyncio.wait_for(
                self._run_conversation_step(request_context, sse_stream),
                timeout=300.0,
            )

            # Normal completion
            await sse_stream.send("complete", {"status": "completed"})
            logger.info("✅ Orchestration completed successfully")

        except asyncio.TimeoutError:
            msg = "Uhh... request timed out (5 mins) while processing your query."
            logger.warning(msg)
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
            # Important: close here to unblock endpoint's `async for`
            await sse_stream.close()

