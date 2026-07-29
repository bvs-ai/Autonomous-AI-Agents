"""Структурований вивід «руками»: схема в промпті + перевірка pydantic.

Агент з 009, але фінальна відповідь має бути JSON за схемою ReturnReport.
Схема вкладена текстом у промпт, валідація — ручний model_validate_json,
на невалідний JSON — ретрай. Як робити це силами SDK, показує 010b.

"""

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

load_dotenv()

client = OpenAI()

RETURN_WINDOW_DAYS = 30


class ReturnItem(BaseModel):
    order_id: str
    days_since_delivery: int
    return_allowed: bool


class ReturnReport(BaseModel):
    items: list[ReturnItem]
    summary: str


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

messages = [
    {
        "role": "system",
        "content": "Фінальну відповідь поверни як JSON за схемою: "
        + json.dumps(ReturnReport.model_json_schema(), ensure_ascii=False),
    },
    {"role": "user", "content": "Які замовлення на поверненні ще можна повернути?"},
]

while True:
    response = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        stream=False,
        messages=messages,
        tools=TOOLS,
        response_format={"type": "json_object"},
    )

    message = response.choices[0].message
    print(f"[LLM_ANSWER] {message.to_json()}\n\n")

    messages.append(message)

    if not message.tool_calls:
        print(f"[RAW_RESPONSE]: {message.content}")
        try:
            report = ReturnReport.model_validate_json(message.content)
        except ValidationError as error:
            print(f"[INVALID_JSON] {error}\n")
            messages.append({"role": "user", "content": f"Відповідь не пройшла валідацію: {error}"})
            continue

        print(f"[FINAL_ANSWER] {report.summary}\n")
        for item in report.items:
            print(f"  {item.order_id}: {item.days_since_delivery} дн., дозволено={item.return_allowed}")
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
