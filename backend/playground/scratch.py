import json

from openai import OpenAI
from config import settings
from common.utils import save_file, print_json
client = OpenAI(api_key=settings.openai.API_KEY)




TICKETS = {
    "T-1001": {
        "customer_id": "C-9",
        "subject": "export hangs at 90%",
        "status": "open",
    },
    "T-1002": {"customer_id": "C-4", "subject": "billing page 404", "status": "open"},
    "T-1003": {"customer_id": "C-9", "subject": "webhook retries", "status": "closed"},
}

CUSTOMERS = {
    "C-9": {"name": "Meridian Ltd", "plan": "enterprise", "mrr": 4200},
    "C-4": {"name": "Bluepine", "plan": "free", "mrr": 0},
}

LOCAL_TOOLS = {
    "list_tickets": lambda status: [
        {"id": k, **v} for k, v in TICKETS.items() if v["status"] == status
    ],
    "get_ticket": lambda ticket_id: TICKETS[ticket_id],
    "get_customer": lambda customer_id: CUSTOMERS[customer_id],
}

TOOL_DEFS = [
    {
        "type": "function",
        "name": "list_tickets",
        "description": "List tickets by status",
        "parameters": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
    },
    {
        "type": "function",
        "name": "get_ticket",
        "description": "Fetch one ticket by id",
        "parameters": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
    },
    {
        "type": "function",
        "name": "get_customer",
        "description": "Fetch a customer record",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    },
]

PTC_TOOLS = [{"type": "programmatic_tool_calling"}] + [
    {**t, "allowed_callers": ["programmatic"]} for t in TOOL_DEFS
]

TASK = (
    "List open tickets, fetch the customer for each, and return JSON: "
    "paying customers only, sorted by MRR descending, "
    "fields: ticket_id, subject, customer_name, mrr."
)

MAX_TOOL_CALLS = 50


def main():
    input_items, trips, tokens, tool_calls = (
        [{"role": "user", "content": TASK}],
        0,
        0,
        0,
    )

    while True:
        response = client.responses.create(
            model="gpt-5.6-terra", input=input_items, tools=PTC_TOOLS
        )
        # print_json(response)
        
        trips += 1
        tokens += response.usage.total_tokens

        for item in response.output:
            if item.type == "program":
                print("--- generated program ---\n", item.code)
                print(type(item.code))

        pending = [i for i in response.output if i.type == "function_call"]
        if not pending:
            print(
                f"\nresult ({trips} round trips, {tokens} tokens):\n",
                response.output_text,
            )
            return

        input_items += response.output

        for call in pending:
            tool_calls += 1
            if tool_calls > MAX_TOOL_CALLS:
                raise RuntimeError("tool budget exceeded")
            result = LOCAL_TOOLS[call.name](**json.loads(call.arguments))
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )


if __name__ == "__main__":
    main()
