from typing import Annotated

from openai import OpenAI, pydantic_function_tool
from pydantic import BaseModel, Field, field_validator, ConfigDict
from config.settings import settings
from common.utils import print_json

client = OpenAI(api_key=settings.openai.API_KEY)

from typing import Annotated

from pydantic import BeforeValidator
from common.pydantic_validators import bounded_confidence


ConfidenceFloat = Annotated[float, bounded_confidence(0.0, 1.0)]


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    value: str
    confidence: ConfidenceFloat = Field(
        ge=-0.5,
        le=1.0,
        description="give a confidence of the response"
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def check_confidence(cls, value):
        print("HERER 2")
        return 1.5
    
print_json(pydantic_function_tool(Response))
print("-----------------------")

completion = client.beta.chat.completions.parse(
    model="gpt-4.1-mini",
    messages=[
        {
            "role": "system",
            "content": (
                "Always call the Response tool.\n"
                "Return confidence = 1.5 exactly."
            ),
        },
        {
            "role": "user",
            "content": "Say hello.",
        },
    ],
    tools=[pydantic_function_tool(Response)],
    tool_choice={
        "type": "function",
        "function": {"name": "Response"},
    },
)


tool_call = completion.choices[0].message.tool_calls[0]

print(type(tool_call.function.parsed_arguments))
print(isinstance(tool_call.function.parsed_arguments, Response))
print(tool_call.function.parsed_arguments)