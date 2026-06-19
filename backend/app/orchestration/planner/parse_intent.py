import logging

from dataclasses import dataclass

from app.common.prompt_loader import load_prompt

from app.common.sse_stream import SSEStream
from clients import OpenAIParserRequest

from app.common.workflow import UserFacingBaseWorkflow, UserFacingOutput
from app.common.messages import UserMessage
from clients.openai_client import OpenAIClient

from typing import Optional
from pydantic import BaseModel, Field
from app.common.messages import AssistantMessage, BaseMessage, ToolMessage
from typing import Annotated
from pydantic import PrivateAttr
import uuid
logger = logging.getLogger(__name__)

SystemGoalDescription = Annotated[str, Field(max_length=100)]

MAX_SYSTEM_GOALS = 10

class SystemGoal(BaseModel):
    _id: str = PrivateAttr(default="")

    description: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="Description of the system goal",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence between 0 and 1 that the system can handle this goal",
    )

    def model_post_init(self, __context: object) -> None:
        object.__setattr__(self, "_id", str(uuid.uuid4())[:8])

    @property
    def id(self) -> str:
        return self._id
    
class InitialParseResult(BaseModel):
    system_goals: list[SystemGoal] = Field(default_factory=list)
    rejected_system_goals: list[SystemGoal] = Field(default_factory=list)
    continue_pipeline: bool = Field(default=False)
    small_talk: Optional[str] = Field(None)
    out_of_scope: Optional[str] = Field(None)
    reasoning: str = Field(default="")
    def to_summary(self) -> dict[str, str | bool | None]:
        return {
            "continue_pipeline": self.continue_pipeline,
            "total_system_goals": len(self.system_goals),
            "num_rejected_system": len(self.rejected_system_goals),
            "num_accepted_system": len(self.system_goals),
            "system_goals": [goal.description for goal in self.system_goals],
            "rejected_system_goals": [goal.description for goal in self.rejected_system_goals],
            "small_talk": self.small_talk,
            "out_of_scope": self.out_of_scope,
        }

    def to_llm_messages(self) -> list[BaseMessage]:
        return [
            AssistantMessage(
                content=self.model_dump_json(
                    include={"small_talk", "out_of_scope", "rejected_system_goals", "continue_pipeline", "reasoning"}
                )
            )
        ]

class InitialParseRequest(BaseModel):
    """
    Initial parse for the Book Recommender: extract system_goals with confidence,
    and separate small_talk and out_of_scope from in-domain requests.
    """
    small_talk: Optional[str] = Field(
        None, min_length=1, max_length=500, description="Small talk in the request"
    )
    out_of_scope: Optional[str] = Field(
        None, min_length=1, max_length=500, description="Out-of-domain content"
    )
    system_goals: list[SystemGoal] = Field(
        default_factory=list,
        max_length=MAX_SYSTEM_GOALS,
        description="System goals for the query",
    )
    reasoning: str = Field(
        ..., min_length=10, max_length=500, description="Reasoning for classification"
    )
    
    async def __call__(self, confident_tuning: float = 0.5) -> InitialParseResult:
        if len(self.system_goals) == 0 and not self.small_talk and not self.out_of_scope:
            logger.warning("Nothing was classified in the initial parse")
            return InitialParseResult(reasoning=self.reasoning)
        
        accepted_system_goals = []
        rejected_system_goals = []
        for goal in self.system_goals:
            if goal.confidence >= confident_tuning and len(accepted_system_goals) < MAX_SYSTEM_GOALS:
                accepted_system_goals.append(goal)
            else:
                reason = (
                    f"Rejected: confidence too low ({goal.confidence})"
                    if goal.confidence < confident_tuning
                    else f"Rejected: exceeded max goals ({MAX_SYSTEM_GOALS})"
                )
                rejected_system_goals.append(
                    goal.model_copy(update={"description": f"{goal.description} — {reason}"})
                )
        
        return InitialParseResult(
            system_goals=accepted_system_goals,
            rejected_system_goals=rejected_system_goals,
            continue_pipeline=len(accepted_system_goals) > 0,
            small_talk=self.small_talk,
            out_of_scope=self.out_of_scope,
            reasoning=self.reasoning
        )


@dataclass(slots=True)
class InitialParseOutput(UserFacingOutput):
    parse_result: InitialParseResult | None = None


class InitialParseWorkflow(UserFacingBaseWorkflow[InitialParseOutput]):
    success_message = "Initial parse completed successfully"
    failure_message = "Initial parse failed"

    system_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_system.txt"
    )
    user_prompt = load_prompt(
        prompt_path="orchestration/planner/prompts/initial_parse_response.txt"
    )

    tool_models = [InitialParseRequest]

    def __init__(
        self, sse_stream: SSEStream, user_message: UserMessage, llm_client: OpenAIClient
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=InitialParseOutput,
        )
        self.user_message = user_message

    async def run(self) -> None:
        await self.sse_stream.send_ui_loading("Thinking...")

        req = OpenAIParserRequest(
            prompt=self.system_prompt,
            messages=[self.user_message],
            tool_models=self.tool_models,
        )
        assistant_msg = await self.run_llm_call(req)

        tool_message = await self.run_tool_call(assistant_msg.tool_calls[0])
        parse_result = InitialParseResult.model_validate(tool_message.content)

        await self.generate_user_response(
            parse_result.to_llm_messages(),
            prompt=self.user_prompt,
        )
        
        self.finalize_result(parse_result)

    def finalize_result(self, parse_result: InitialParseResult) -> None:
        self.output.parse_result = parse_result
        self.output.summary = parse_result.to_summary()
        super().finalize_result(
            ok=bool(parse_result.continue_pipeline and parse_result.system_goals)
        )
