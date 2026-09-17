from openai import OpenAI
from config import settings
from common.utils import save_file, print_json
client = OpenAI(api_key=settings.openai.API_KEY)
import time

import json
model = "gpt-5.6"

system_prompt = """
<tool_orchestration>
Use Programmatic Tool Calling to compare inventory with demand for sku_123
using only get_inventory and get_demand. Run both calls concurrently. Use
only documented tool input and output fields.

Process and reduce the intermediate results, then emit exactly one JSON object
with sku, available_units, requested_units, and shortage_units, where
shortage_units is max(requested_units - available_units, 0). Include
available_units and requested_units as evidence for the calculation.

Stop when both tool results contain the required fields. Retry transient
failures at most 1 time. Do not repeat completed calls or perform
side-effecting actions. If a required result is still missing, return a clear
structured failure.

Use direct tool calls only for approval before any inventory-changing action.
</tool_orchestration>
"""



def get_inventory(sku):
    return {"sku": sku, "available_units": 42}


def get_demand(sku):
    return {"sku": sku, "requested_units": 31}

def get_user(id):
    return {"id": id, "name": "hello"}


implementations = {
    "get_inventory": get_inventory,
    "get_demand": get_demand,
}

tools = [
    {
        "type": "function",
        "name": "get_inventory",
        "description": "Return an object with sku (string) and available_units (number).",
        "parameters": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "available_units": {"type": "number"},
            },
            "required": ["sku", "available_units"],
            "additionalProperties": False,
        },
        "allowed_callers": ["programmatic"],
    },
    {
        "type": "function",
        "name": "get_demand",
        "description": "Return an object with sku (string) and requested_units (number).",
        "parameters": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "requested_units": {"type": "number"},
            },
            "required": ["sku", "requested_units"],
            "additionalProperties": False,
        },
        "allowed_callers": ["programmatic"],
    },
    {"type": "programmatic_tool_calling"},
]

input_items = [
    {
        "role": "system",
        "content": system_prompt
    },
    {
        "role": "user",
        "content": "Compare inventory with demand for sku_123.",
    }
]

start = time.perf_counter()
previous_id = None
pending_items = input_items
while True:
    payload = {
        "model": model,
        "tools": tools,
        "previous_response_id": previous_id,
        "input": pending_items,
    }

    # print("========== REQUEST ==========")
    # print(json.dumps(payload, indent=2))

    response = client.responses.create(**payload)
    previous_id = response.id
    # print("id:", previous_id)
    # print("pending_items:", len(pending_items))
    
    print_json(response)

    if response.status != "completed":
        raise RuntimeError(f"Response ended with status {response.status}")

    # Preserve every output item, including program and reasoning items.
    pending_items = []

    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        message = next(
            (item for item in response.output if item.type == "message"), None
        )
        if message:
            refusal = next(
                (part.refusal for part in message.content if part.type == "refusal"),
                "",
            )
            print(response.output_text or refusal)
            break
        continue

    for call in calls:
        run = implementations.get(call.name)
        if run is None:
            raise ValueError(f"Unknown tool: {call.name}")

        result = run(**json.loads(call.arguments))
        # print("call:", type(call))
        # print("call.caller:", type(call.caller))
        pending_items.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result),
                # Preserve caller so the runtime can resume the correct program.
                "caller": call.caller if call.caller else None,
            }
        )
        
elapsed = time.perf_counter() - start

print(f"Response time: {elapsed:.3f}s")
print("------------------------------------")


input_items = [
    {
        "role": "system",
        "content": system_prompt
    },
    {
        "role": "user",
        "content": "Compare inventory with demand for sku_345.",
    }
]


start = time.perf_counter()
previous_id = None
pending_items = input_items
while True:
    payload = {
        "model": model,
        "tools": tools,
        "previous_response_id": previous_id,
        "input": pending_items,
    }

    # print("========== REQUEST ==========")
    # print(json.dumps(payload, indent=2))

    response = client.responses.create(**payload)
    previous_id = response.id
    # print("id:", previous_id)
    # print("pending_items:", len(pending_items))
    
    print_json(response)

    if response.status != "completed":
        raise RuntimeError(f"Response ended with status {response.status}")

    # Preserve every output item, including program and reasoning items.
    pending_items = []

    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        message = next(
            (item for item in response.output if item.type == "message"), None
        )
        if message:
            refusal = next(
                (part.refusal for part in message.content if part.type == "refusal"),
                "",
            )
            print(response.output_text or refusal)
            break
        continue

    for call in calls:
        run = implementations.get(call.name)
        if run is None:
            raise ValueError(f"Unknown tool: {call.name}")

        result = run(**json.loads(call.arguments))
        # print("call:", type(call))
        # print("call.caller:", type(call.caller))
        pending_items.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result),
                # Preserve caller so the runtime can resume the correct program.
                "caller": call.caller if call.caller else None,
            }
        )
        
elapsed = time.perf_counter() - start

print(f"Response time: {elapsed:.3f}s")