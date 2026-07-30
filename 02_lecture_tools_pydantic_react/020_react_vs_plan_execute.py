"""ReAct проти Plan-and-Execute на тій самій задачі: "Перевір усі замовлення
на поверненні і скажи, які ще можна повернути".

Обидва варіанти нижче -- СКРИПТОВАНІ емуляції (без реального LLM), що показують
РІЗНИЦЮ В ФОРМІ виконання, а не поведінку конкретної моделі:

  - pure_react_trial(): крок за кроком, без плану. Кожен крок -- окреме "рішення"
    (тут: із заданою ймовірністю моделі "забути" викликати check_return_policy
    одразу і повторити query_orders замість цього) -- звідси розкид кількості
    кроків між прогонами. Ілюструє: дальні залежності (перевір-кожне-знайдене)
    тримаються гірше, кроки непередбачувані.

  - plan_and_execute(): Planner спершу будує явний список кроків (видно ДО
    виконання -- краща debuggability), Executor виконує його без відхилень,
    Replanner не потрібен, бо дані узгоджені з планом із першого разу.

Порівнюємо не "хто переміг", а стабільність кількості кроків між прогонами.
"""

import random

ORDERS = [
    {"id": "A-1001", "status": "повернення", "days_since_delivery": 3},
    {"id": "A-1002", "status": "повернення", "days_since_delivery": 45},
    {"id": "A-1003", "status": "доставлено", "days_since_delivery": 1},
    {"id": "A-1004", "status": "повернення", "days_since_delivery": 12},
]


def query_orders(status: str) -> list[dict]:
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id: str) -> dict:
    order = next(o for o in ORDERS if o["id"] == order_id)
    return {"order_id": order_id, "return_allowed": order["days_since_delivery"] <= 30}


def pure_react_trial(seed: int) -> tuple[dict, list[str]]:
    """Емуляція одного прогону ReAct без плану: модель може "передумати" й
    повторити query_orders замість переходу до наступного check_return_policy."""
    rng = random.Random(seed)
    trace = []
    returning = query_orders("повернення")
    trace.append("query_orders")

    results = []
    for order in returning:
        # "Модель" з певною ймовірністю спершу повторює query_orders -- зайвий крок,
        # характерний саме для ReAct без явного плану (немає "чек-листа" наперед).
        if rng.random() < 0.4:
            query_orders("повернення")
            trace.append("query_orders (зайвий повтор)")

        trace.append(f"check_return_policy({order['id']})")
        results.append(check_return_policy(order["id"]))

    return {"count": len(results)}, trace


def plan_and_execute() -> tuple[dict, list[str]]:
    """Planner будує повний список кроків ДО виконання; Executor лише проходить його."""
    returning = query_orders("повернення")
    plan = ["query_orders"] + [f"check_return_policy({o['id']})" for o in returning]

    results = [check_return_policy(o["id"]) for o in returning]
    return {"count": len(results)}, plan


if __name__ == "__main__":
    print("[REACT] 3 прогони поспіль -- кількість кроків нестабільна:")
    for seed in (1, 2, 3):
        result, trace = pure_react_trial(seed)
        print(f"    seed={seed}: {len(trace)} крок(и) -- {trace}")

    print("\n[PLAN_AND_EXECUTE] план видно ДО виконання, кроки стабільні між прогонами:")
    for _ in range(3):
        result, plan = plan_and_execute()
        print(f"    {len(plan)} крок(и) -- {plan}")

    print("\n[ВИСНОВОК] ReAct: 1-3 кроки на об'єкт, залежність від попереднього кроку,")
    print("           прийнятно для коротких/інтерактивних задач.")
    print("           Plan-and-Execute: план фіксований і видимий заздалегідь -- краще")
    print("           для довгих ланцюжків із дальніми залежностями та вимогами SLA.")
