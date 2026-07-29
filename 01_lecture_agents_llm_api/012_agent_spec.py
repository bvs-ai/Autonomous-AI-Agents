"""Agent Spec — контракт агента, а не «гарний промпт».

Три запуски на лекції:

    SPEC=0 python 012_agent_spec.py            # без контракту: порядок дій випадковий
    SPEC=1 python 012_agent_spec.py            # з контрактом: політики задають порядок
    SPEC=1 python 012_agent_spec.py non_goal   # прохання поза межами -> агент відмовляє

Усі шість компонентів контракту зібрані в AGENT_SPEC нижче:
Goal / Tools / Policies / Constraints (+ non-goals) / Completion / Output.
Це артефакт, який версіонується і проходить рев'ю, а не рядок усередині f-string.
"""

import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

WITH_SPEC = os.getenv("SPEC", "1") == "1"
MAX_ITERATIONS = 6
RETURN_WINDOW_DAYS = 30

AGENT_SPEC = f"""
Ти агент підтримки інтернет-магазину. Версія специфікації: 1.2.

МЕТА (verifiable goal):
Для кожного замовлення зі статусом 'повернення' визначити, чи вкладається воно
у вікно повернення ({RETURN_WINDOW_DAYS} днів), і повернути підсумок користувачеві.

ІНСТРУМЕНТИ:
- query_orders(status) — список замовлень за статусом
- check_return_policy(order_id) — перевірка вікна повернення для одного замовлення

ПОЛІТИКИ (порядок дій):
1. Спочатку ЗАВЖДИ query_orders — не вигадуй ідентифікатори замовлень.
2. Далі check_return_policy ОКРЕМО для кожного знайденого замовлення.
3. Не роби висновок про можливість повернення самостійно за датою — лише за
   результатом check_return_policy.

ОБМЕЖЕННЯ:
- Максимум {MAX_ITERATIONS} кроків.
- Лише операції читання. Жодних змін у замовленнях.
- Дані брати виключно з інструментів; якщо даних немає — так і сказати.

NON-GOALS (чого агент НЕ робить):
- не оформлює повернення і не змінює статус замовлення;
- не спілкується з клієнтом і не надсилає листів;
- не обіцяє компенсацій, знижок чи термінів.
Якщо просять зробити щось із цього — ввічливо відмов і поясни межі своїх повноважень.

КРИТЕРІЙ ЗАВЕРШЕННЯ:
Для КОЖНОГО замовлення зі списку є результат check_return_policy.

ФОРМАТ ВИВОДУ:
Спочатку рядок-підсумок, потім список: <id> — <днів> дн. — дозволено/ні.
"""

NO_SPEC = "Ти помічник підтримки інтернет-магазину."


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

TASKS = {
    "ok": "Які замовлення на поверненні ще можна повернути?",
    # Прохання виходить за межі NON-GOALS: із контрактом агент має відмовити.
    "non_goal": "Оформи повернення для A-1004 і напиши клієнту, що гроші будуть завтра.",
}

task = TASKS[sys.argv[1] if len(sys.argv) > 1 else "ok"]

print(f"[SPEC] {'увімкнена' if WITH_SPEC else 'ВИМКНЕНА'}")
print(f"[TASK] {task}\n")

messages = [
    {"role": "system", "content": AGENT_SPEC if WITH_SPEC else NO_SPEC},
    {"role": "user", "content": task},
]

step = 0

while True:
    step += 1
    if step > MAX_ITERATIONS:
        print(f"[STOPPED_BY_LIMIT] вичерпано {MAX_ITERATIONS} кроків\n")
        break

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
        args = json.loads(call.function.arguments)
        print(f"[TOOL_CALL] {name}({args})")
        result = TOOL_FUNCTIONS[name](**args)
        print(f"[TOOL_CALL_RESULT] {result}\n")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

# Порівняння двох запусків:
#   SPEC=0 — агент може відповісти «на око», пропустити check_return_policy
#            або перевірити не всі замовлення; формат відповіді щоразу інший.
#   SPEC=1 — порядок викликів заданий політиками, критерій завершення перевіряється,
#            формат стабільний, а прохання поза межами отримує відмову.
