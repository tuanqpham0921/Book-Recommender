"""Playground: exercise the coercion field types from app.domains.field_types —
first locally with raw LLM-ish garbage, then against a real tool call where
the LLM is instructed to return bad values."""

from openai import OpenAI, pydantic_function_tool
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from common.utils import print_json
from app.domains.field_types import (
    ConfidenceFloat,
    DescriptionStr,
    ReasoningStr,
    OptionalStr,
)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: DescriptionStr = Field(
        description="Description of what the user asked for"
    )
    reasoning: ReasoningStr = Field(
        description="Thought process behind the response"
    )
    value: OptionalStr = Field(
        description="Optional extra note; null if none"
    )
    confidence: ConfidenceFloat = Field(
        description="Confidence of the response between 0 and 1"
    )


# --- local demo: raw values an LLM might plausibly return -------------------

cases = {
    "short strings pass through": dict(
        description="short", reasoning="ok", value="hi", confidence=0.9
    ),
    "blank/None -> fallback sentinel (required) or None (optional)": dict(
        description="", reasoning=None, value="   ", confidence=1.5
    ),
    "non-strings salvaged via str(), bad confidence -> 0.0": dict(
        description=12345, reasoning=["a", "b"], value=42, confidence="high"
    ),
    "over-length truncated to 500 with ...": dict(
        description="x" * 600, reasoning="fine", value="y" * 600, confidence=1
    ),
}

for label, raw in cases.items():
    parsed = Response.model_validate(raw)
    print(f"--- {label}")
    for field, out in parsed.model_dump().items():
        shown = f"str len={len(out)}, ends {out[-6:]!r}" if isinstance(out, str) and len(out) > 60 else repr(out)
        print(f"  {field}: {shown}")

# --- LLM demo: instruct the model to violate the schema on purpose ----------

print("\n=== tool schema sent to the LLM ===")
print_json(pydantic_function_tool(Response))

client = OpenAI(api_key=settings.openai.API_KEY)

completion = client.beta.chat.completions.parse(
    model="gpt-4.1-mini",
    messages=[
        {
            "role": "system",
            "content": (
                "Always call the Response tool.\n"
                "Return confidence = 1.5 exactly, value = null, "
                "and reasoning = an empty string."
            ),
        },
        {
            "role": "user",
            "content": "Don't say anything",
        },
    ],
    tools=[pydantic_function_tool(Response)],
    tool_choice={
        "type": "function",
        "function": {"name": "Response"},
    },
)

tool_call = completion.choices[0].message.tool_calls[0]

print("\n=== raw arguments from the LLM ===")
print(tool_call.function.arguments)
print("\n=== after validators ===")
print(tool_call.function.parsed_arguments)
