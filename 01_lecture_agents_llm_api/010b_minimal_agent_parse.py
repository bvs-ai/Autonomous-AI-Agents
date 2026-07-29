"""Те саме, що 010, але структурований вивід робить SDK, а не промпт.

Чотири речі, які тут інакші, ніж у 010:
  1. схема НЕ вкладається текстом у system-промпт;
     її будує SDK з Pydantic-моделі -> response_format=ReturnReport
  2. інструменти описані Pydantic-моделями через pydantic_function_tool(),
     а не рукописними JSON-словниками
  3. відповідь приходить уже об'єктом: message.parsed; відмова -> message.refusal
  4. аргументи інструмента теж уже провалідовані: call.function.parsed_arguments

Немає ні ручного model_validate_json, ні ретраїв на невалідний JSON:
провайдер гарантує схему (strict json_schema).

    фаза 1: .parse(tools=...)                  -> ReAct-цикл, збір фактів
    фаза 2: .parse(response_format=...)        -> фінальний звіт за схемою

"""

import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI, pydantic_function_tool
from pydantic import BaseModel, Field

load_dotenv()

client = OpenAI()
MODEL = os.environ["LLM_MODEL"]

RETURN_WINDOW_DAYS = 30


# --- Схема фінальної відповіді -------------------------------------------------


class ReturnItem(BaseModel):
    order_id: str
    days_since_delivery: int
    return_allowed: bool


class ReturnReport(BaseModel):
    items: list[ReturnItem]
    summary: str


# --- Інструменти як Pydantic-моделі --------------------------------------------


class QueryOrders(BaseModel):
    """Отримати список замовлень із заданим статусом."""

    status: str = Field(description="Статус українською: 'повернення' або 'доставлено'")


class CheckReturnPolicy(BaseModel):
    """Перевірити, чи можна ще повернути замовлення."""

    order_id: str = Field(description="Ідентифікатор замовлення, напр. 'A-1001'")


def days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


def query_orders(args: QueryOrders):
    return [o for o in ORDERS if o["status"] == args.status]


def check_return_policy(args: CheckReturnPolicy):
    order = next((o for o in ORDERS if o["id"] == args.order_id), None)
    if order is None:
        return {"error": f"Замовлення {args.order_id} не знайдено"}

    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {
        "order_id": args.order_id,
        "days_since_delivery": days,
        "return_window_days": RETURN_WINDOW_DAYS,
        "return_allowed": days <= RETURN_WINDOW_DAYS,
    }


TOOL_FUNCTIONS = {
    "QueryOrders": query_orders,
    "CheckReturnPolicy": check_return_policy,
}

# Замість рукописних JSON-схем: SDK робить їх сам, ще й зі "strict": true.
TOOLS = [pydantic_function_tool(QueryOrders), pydantic_function_tool(CheckReturnPolicy)]


# --- Агентний цикл -------------------------------------------------------------

messages = [
    {"role": "system", "content": "Ти асистент підтримки. Відповідай на основі даних з інструментів."},
    {"role": "user", "content": "Які замовлення на поверненні ще можна повернути?"},
]

# Фаза 1: звичайний ReAct-цикл з інструментами, без response_format.
while True:
    message = client.chat.completions.parse(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
    ).choices[0].message

    messages.append(message)

    if not message.tool_calls:
        print(f"[DRAFT_ANSWER] {message.content}\n")
        break

    for call in message.tool_calls:
        args = call.function.parsed_arguments  # уже Pydantic-об'єкт, не рядок JSON
        print(f"[TOOL_CALL] {call.function.name}({args})\n")
        result = TOOL_FUNCTIONS[call.function.name](args)
        print(f"[TOOL_CALL_RESULT] {result}\n")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

# Фаза 2: той самий контекст, але вже під схему — без інструментів.
messages.append({"role": "user", "content": "Оформи підсумок як структурований звіт."})

message = client.chat.completions.parse(
    model=MODEL,
    messages=messages,
    response_format=ReturnReport,
).choices[0].message

# Відмова моделі — окреме поле, а не сміття замість JSON.
if message.refusal:
    print(f"[REFUSAL] {message.refusal}")
else:
    report = message.parsed
    print(f"[FINAL_ANSWER] {report.summary}\n")
    for item in report.items:
        print(f"  {item.order_id}: {item.days_since_delivery} дн., дозволено={item.return_allowed}")
