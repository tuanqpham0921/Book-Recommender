from typing import Any

from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow
from ..schemas.output_schemas import FindByTitleOutput
from app.common.messages import AssistantMessage, APIMessage, ToolMessage, UserMessage
from clients.base import BaseLLMClient

class FindByTitle(AppBaseWorkflow[FindByTitleOutput]):
    ui_loading_message = "Getting Book By Title..."

    async def run(self):
        # 0. send a UI loading message
        # 1. call the args parser here
        # 2. Update the UI message to f"Getting book title: {...}"
        # 3. do a query to db
        #    * build the statement
        #    * do a qeury with just count
        #    * populate the output with found numbers
        #    * return the CTE as a step
        # 4. finalize the output
        #    * check if there are atleast 1 book
        #    * maybe stamp on the UI with the reference book
        
        ...