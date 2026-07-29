"""Два інструменти замість одного — і в агента з'являється справжній вибір.

query_orders + check_return_policy: порядок і кількість викликів вирішує модель,
а не наш код. У логах вперше видно повний цикл Think -> Act -> Observe.

"""

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

RETURN_WINDOW_DAYS = 30


def days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


def query_orders(status):
    """Повертає список замовлень із заданим статусом."""
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id):
    """Перевіряє, чи вкладається замовлення у вікно повернення."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}

    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {
        "order_id": order_id,
        "days_since_delivery": days,
        "return_window_days": RETURN_WINDOW_DAYS,
        "return_allowed": days <= RETURN_WINDOW_DAYS,
    }


TOOL_FUNCTIONS = {
    "query_orders": query_orders,
    "check_return_policy": check_return_policy,
}

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
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_policy",
            "description": "Перевірити, чи можна ще повернути замовлення.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Ідентифікатор замовлення, напр. 'A-1001'",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
]

messages = [{"role": "user", "content": "Які замовлення на поверненні ще можна повернути?"}]

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
