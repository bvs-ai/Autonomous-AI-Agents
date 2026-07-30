"""Thin vs Smart vs Orchestrator tools -- одна й та сама задача, три способи розрізати
складність між моделлю (більше кроків/reasoning) і кодом (більше реалізації/тестів).

Задача: "Скільки замовлень на поверненні можна повернути, і скільки грошей це на суму?"

  - THIN: query_orders + check_return_policy + get_order_amount -- три атомарні
    інструменти. Модель сама вирішує порядок і кількість викликів (тут -- емуляція
    циклу агента без реального LLM, щоб порахувати кроки детерміновано).
  - SMART: один get_returnable_orders_summary() -- уся логіка (фільтр + перевірка
    вікна + сума) в коді. Один крок, але немає гнучкості: якщо завтра треба
    "тільки перші 2 замовлення" -- це вже інша сигнатура інструмента.
  - ORCHESTRATOR: process_return_batch() -- обгортає ті самі thin-інструменти
    послідовністю "знайти -> перевірити кожне -> підсумувати", але лишає видимою
    структуру кроків (для аудиту) і повертає структуровані часткові помилки.

Головне порівняння -- не "що краще", а "де лежить складність" (рахуємо кроки).
"""

from datetime import date, timedelta

RETURN_WINDOW_DAYS = 30


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3), "amount_usd": 42.0},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45), "amount_usd": 99.5},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1), "amount_usd": 15.0},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12), "amount_usd": 30.0},
]


# ---------------------------------------------------------------------------
# THIN TOOLS -- атомарні, композиційні, дешеві в реалізації, дорогі в оркестрації.
# ---------------------------------------------------------------------------
def query_orders(status: str) -> list[dict]:
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id: str) -> dict:
    order = next(o for o in ORDERS if o["id"] == order_id)
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "return_allowed": days <= RETURN_WINDOW_DAYS}


def get_order_amount(order_id: str) -> float:
    return next(o for o in ORDERS if o["id"] == order_id)["amount_usd"]


def thin_agent_simulation() -> tuple[dict, int]:
    """Емуляція того, скільки викликів інструментів робить агент з thin-набором:
    1 виклик query_orders + по 2 виклики (policy + amount) на кожне знайдене замовлення."""
    steps = 0

    steps += 1
    returning = query_orders("повернення")

    total = 0.0
    count = 0
    for order in returning:
        steps += 1
        policy = check_return_policy(order["id"])
        if policy["return_allowed"]:
            steps += 1
            total += get_order_amount(order["id"])
            count += 1

    return {"count": count, "total_usd": total}, steps


# ---------------------------------------------------------------------------
# SMART TOOL -- уся логіка "в одному флаконі": детермінізм і тестованість,
# але менше гнучкості (нова вимога = нова сигнатура або новий інструмент).
# ---------------------------------------------------------------------------
def get_returnable_orders_summary() -> dict:
    """Один виклик: фільтр статусу + перевірка вікна + сума -- усе в коді інструмента."""
    returning = [o for o in ORDERS if o["status"] == "повернення"]
    returnable = [
        o for o in returning
        if (date.today() - date.fromisoformat(o["delivered_at"])).days <= RETURN_WINDOW_DAYS
    ]
    return {"count": len(returnable), "total_usd": sum(o["amount_usd"] for o in returnable)}


def smart_agent_simulation() -> tuple[dict, int]:
    return get_returnable_orders_summary(), 1  # рівно один крок агента


# ---------------------------------------------------------------------------
# ORCHESTRATOR TOOL -- інкапсулює типову послідовність thin-викликів в один
# виклик агента, але лишає кроки видимими (для аудиту) і повертає часткові помилки
# структуровано, а не як "чорний ящик".
# ---------------------------------------------------------------------------
def process_return_batch() -> dict:
    trace = []
    total = 0.0
    count = 0

    returning = query_orders("повернення")
    trace.append({"step": "query_orders", "found": len(returning)})

    for order in returning:
        try:
            policy = check_return_policy(order["id"])
        except Exception as error:  # noqa: BLE001 -- навчальний приклад часткової помилки
            trace.append({"step": "check_return_policy", "order_id": order["id"], "error": str(error)})
            continue

        trace.append({"step": "check_return_policy", "order_id": order["id"], "result": policy})
        if policy["return_allowed"]:
            amount = get_order_amount(order["id"])
            trace.append({"step": "get_order_amount", "order_id": order["id"], "amount_usd": amount})
            total += amount
            count += 1

    return {"summary": {"count": count, "total_usd": total}, "trace": trace}


def orchestrator_agent_simulation() -> tuple[dict, int]:
    return process_return_batch(), 1  # 1 крок агента, кроки всередині -- у trace


if __name__ == "__main__":
    for label, fn in [
        ("THIN", thin_agent_simulation),
        ("SMART", smart_agent_simulation),
        ("ORCHESTRATOR", orchestrator_agent_simulation),
    ]:
        result, steps = fn()
        print(f"[{label}] кроків агента: {steps}")
        print(f"[{label}] результат: {result}\n")

    # Межа застосовності. Новий запит з «довгого хвоста»:
    # "на яку суму замовлення A-1004?" -- одне число, без жодних перевірок.
    print("[ІНШИЙ ЗАПИТ] 'На яку суму замовлення A-1004?'")
    print(f"    THIN: 1 крок, інструмент уже є -> {get_order_amount('A-1004')}")
    print("    SMART/ORCHESTRATOR: 0 придатних інструментів -- їхні сигнатури фіксовані")
    print("    під сценарій 'усі замовлення на поверненні'. Потрібен новий інструмент,")
    print("    тобто новий реліз коду.\n")
    print("Звідси комбінований підхід у проді: база thin-інструментів на весь домен")
    print("плюс кілька orchestrator саме на ті сценарії, що повторюються щодня.")
