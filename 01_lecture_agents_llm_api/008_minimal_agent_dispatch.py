"""Той самий агент, що в 007, але виклик інструмента — через диспетчер.

Словник TOOL_FUNCTIONS замість if/elif: інструмент стає звичайною Python-функцією,
і додати новий — це один рядок, а не гілка в циклі.

"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

ORDERS = [
    {"id": "A-1001", "status": "повернення", "days_since_delivery": 3},
    {"id": "A-1002", "status": "повернення", "days_since_delivery": 45},
    {"id": "A-1003", "status": "доставлено", "days_since_delivery": 1},
    {"id": "A-1004", "status": "повернення", "days_since_delivery": 12},
]


def query_orders(status):
    """Повертає список замовлень із заданим статусом."""
    return [o for o in ORDERS if o["status"] == status]


TOOL_FUNCTIONS = {"query_orders": query_orders}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Отримати список замовлень із заданим статусом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Статус українською: 'повернення' або 'доставлено'",
                    }
                },
                "required": ["status"],
            },
        },
    }
]

messages = [{"role": "user", "content": "Які замовлення зараз на поверненні? Перелічи їхні id."}]

while True:
    response = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        stream=False,
        messages=messages,
        tools=TOOLS,
    )

    message = response.choices[0].message
    print(f"[LLM_ANSWER] {message.to_json()}\n\n")

    messages.append(message)

    if not message.tool_calls:
        print(f"[FINAL_ANSWER] {message.content}\n")
        break

    for call in message.tool_calls:
        name = call.function.name
        args = json.loads(call.function.arguments)
        print(f"[TOOL_CALL] {name}({args})\n")
        result = TOOL_FUNCTIONS[name](**args)
        print(f"[TOOL_CALL_RESULT] {result}\n")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
