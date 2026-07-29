"""Той самий агент, що і в 009, але обкладений запобіжниками.

Два варыанта запуски:

    GUARDRAILS=0 python 011_agent_limits_guardrails.py trap   # цикл без гальм
    GUARDRAILS=1 python 011_agent_limits_guardrails.py trap   # з гальмами

Чотири запобіжники:
  1. ліміт ітерацій   -> зупинка [STOPPED_BY_LIMIT] != [FINAL_ANSWER]
  2. allowlist        -> невідомий інструмент повертається як observation, а не падає
  3. валідація        -> аргументи перевіряються ДО виконання
  4. no-progress      -> повторний однаковий виклик ловиться детектором
"""

import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

GUARDRAILS = os.getenv("GUARDRAILS", "1") == "1"
MAX_ITERATIONS = 6
RETURN_WINDOW_DAYS = 30
ALLOWED_STATUSES = {"повернення", "доставлено"}


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
    if status not in ALLOWED_STATUSES:
        # Логічна помилка: не кидаємо виняток, а повертаємо її агентові як observation.
        raise ValueError(f"Невідомий статус '{status}'. Доступні: {sorted(ALLOWED_STATUSES)}")
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id):
    """Перевіряє, чи вкладається замовлення у вікно повернення."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        raise ValueError(f"Замовлення {order_id} не знайдено")

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

TASKS = {
    "ok": "Які замовлення на поверненні ще можна повернути?",
    # Пастка: таких замовлень у базі немає. Без запобіжників агент схильний
    # перебирати статуси та повторювати ті самі виклики нескінченно.
    "trap": "Скільки замовлень зі статусом 'скасовано'? Обов'язково знайди їх.",
}

task = TASKS[sys.argv[1] if len(sys.argv) > 1 else "ok"]
messages = [{"role": "user", "content": task}]

print(f"[GUARDRAILS] {'увімкнені' if GUARDRAILS else 'ВИМКНЕНІ'}")
print(f"[TASK] {task}\n")

seen_calls = set()  # (3) no-progress detector: які виклики вже робилися
step = 0

while True:
    step += 1

    # (1) Ліміт ітерацій: не «щоб було», а щоб зупинитися, поки не стало гірше.
    if GUARDRAILS and step > MAX_ITERATIONS:
        print(f"[STOPPED_BY_LIMIT] вичерпано {MAX_ITERATIONS} ітерацій без результату")
        print("[STATUS] це ВИМУШЕНА зупинка, а не успішне завершення — у логах різні стани\n")
        break

    print(f"--- крок {step} ---")

    response = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        stream=False,
        messages=messages,
        tools=TOOLS,
    )

    message = response.choices[0].message
    messages.append(message)

    if not message.tool_calls:
        print(f"[FINAL_ANSWER] {message.content}\n")
        break

    for call in message.tool_calls:
        name = call.function.name
        raw_args = call.function.arguments
        print(f"[TOOL_CALL] {name}({raw_args})")

        # Результат кроку в будь-якому разі повертається моделі як observation:
        # помилка — теж інформація, на якій агент може виправитися.
        if GUARDRAILS:
            signature = f"{name}:{raw_args}"

            if name not in TOOL_FUNCTIONS:
                # (2) Allowlist: галюцинація дії не валить процес.
                observation = {
                    "error": f"Інструмент '{name}' не існує",
                    "available_tools": sorted(TOOL_FUNCTIONS),
                }
            elif signature in seen_calls:
                # (3) Той самий виклик удруге = прогресу немає.
                observation = {
                    "error": "Цей самий виклик з тими самими аргументами вже робився",
                    "hint": "Результат не зміниться. Зміни стратегію або завершуй відповідь.",
                }
            else:
                seen_calls.add(signature)
                try:
                    observation = TOOL_FUNCTIONS[name](**json.loads(raw_args))
                except Exception as error:  # noqa: BLE001 — навчальний приклад
                    observation = {"error": f"{type(error).__name__}: {error}"}
        else:
            # Без запобіжників: невідомий інструмент або погані аргументи = виняток і падіння.
            observation = TOOL_FUNCTIONS[name](**json.loads(raw_args))

        print(f"[TOOL_CALL_RESULT] {observation}\n")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(observation, ensure_ascii=False, default=str),
            }
        )
