"""Той самий агент, що в 009 лекції 1 (query_orders + check_return_policy),
але схема інструментів будується з Pydantic-моделей (002) через адаптер to_strict
з 005 і викликається у СТРОГОМУ режимі OpenAI: strict=True,
additionalProperties:false, parallel_tool_calls=False.

Що це дає порівняно з 009: гарантію дає constrained decoding -- модель фізично
не може згенерувати токени поза граматикою схеми (немає зайвих полів, значення
status лише з enum), а не «переконлива» схема в промпті.

У лекції 1 те саме вже було, але з іншого боку: 010b застосовував strict до
ФІНАЛЬНОЇ відповіді (response_format), і там же ми зʼясували, що це фіча рушія
інференсу, а не «розуму» моделі -- на дешевих маршрутах вона просто відсутня.
Тут той самий механізм застосовується до АРГУМЕНТІВ інструмента, і застереження
теж лишається тим самим: якщо модель за шлюзом не вміє strict, буде 400.

Потребує заповненого .env і моделі з підтримкою strict tool calling.
"""

import json
import os
from datetime import date, timedelta
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

client = OpenAI()
MODEL = os.environ["LLM_MODEL"]


class QueryOrdersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["повернення", "доставлено"] = Field(description="Статус замовлення")


class CheckReturnPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^A-\d{4}$", description="Ідентифікатор замовлення, напр. 'A-1001'")


def to_strict(model: type[BaseModel]) -> dict:
    """Той самий адаптер, що й у 005 (тут полів без default -- тому коротший)."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    for prop in schema["properties"].values():
        prop.pop("title", None)
    schema["required"] = list(schema["properties"])
    return schema


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Отримати список замовлень із заданим статусом.",
            "strict": True,
            "parameters": to_strict(QueryOrdersInput),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_policy",
            "description": "Перевірити, чи можна ще повернути замовлення.",
            "strict": True,
            "parameters": to_strict(CheckReturnPolicyInput),
        },
    },
]


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


def query_orders(status):
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id):
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= 30}


TOOL_FUNCTIONS = {"query_orders": query_orders, "check_return_policy": check_return_policy}

if __name__ == "__main__":
    messages = [{"role": "user", "content": "Які замовлення на поверненні ще можна повернути?"}]

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=False,  # разом зі strict -- рівно 0 або 1 виклик за раз
        )

        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            print(f"[FINAL_ANSWER] {message.content}")
            break

        for call in message.tool_calls:
            args = json.loads(call.function.arguments)  # strict гарантує валідність проти схеми
            print(f"[TOOL_CALL] {call.function.name}({args})")
            result = TOOL_FUNCTIONS[call.function.name](**args)
            print(f"[TOOL_CALL_RESULT] {result}\n")
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)}
            )
