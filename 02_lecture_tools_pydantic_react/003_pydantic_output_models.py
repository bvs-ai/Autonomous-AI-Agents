"""Валідація виходу: гарантувати, що інструмент ніколи не поверне «дивний» формат,
який зламає наступний крок агента.

Увага, це НЕ те саме, що 010 лекції 1. Там Pydantic перевіряв ФІНАЛЬНУ відповідь
моделі (ReturnReport) -- тобто останній крок, вихід агента назовні. Тут схема
стоїть на КОЖНОМУ виклику інструмента, тобто всередині циклу: якщо API замовлень
раптом віддасть інше поле, це впіймається одразу, а не за три кроки потому у
вигляді незрозумілої фінальної відповіді.

Ті самі query_orders / check_return_policy з лекції 1 (006-012), але тепер
результат перед поверненням проганяється через OrderRecord / ReturnPolicyResult:
model_validate(raw) -- сире -> модель, model_dump(mode="json") -- назад у
JSON-ready структуру, яку відправимо моделі як вміст tool-повідомлення.
"""

import json
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RETURN_WINDOW_DAYS = 30


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


class OrderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    delivered_at: date


class QueryOrdersOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[OrderRecord]
    total_found: int = Field(ge=0)


class ReturnPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    days_since_delivery: int = Field(ge=0)
    return_window_days: int
    return_allowed: bool


def query_orders(status: str) -> dict:
    """Повертає список замовлень із заданим статусом -- вихід гарантовано валідний."""
    raw = {"orders": [o for o in ORDERS if o["status"] == status]}
    raw["total_found"] = len(raw["orders"])

    try:
        validated = QueryOrdersOutput.model_validate(raw)
    except ValidationError:
        # У проді -- перетворити на стандартизований error-контейнер (ok=false)
        # і повернути моделі замість краху; тут піднімаємо далі навчально.
        raise

    return validated.model_dump(mode="json")


def check_return_policy(order_id: str) -> dict:
    """Перевіряє вікно повернення -- результат теж проходить через output-схему."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}

    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    raw = {
        "order_id": order_id,
        "days_since_delivery": days,
        "return_window_days": RETURN_WINDOW_DAYS,
        "return_allowed": days <= RETURN_WINDOW_DAYS,
    }
    validated = ReturnPolicyResult.model_validate(raw)
    return validated.model_dump(mode="json")


if __name__ == "__main__":
    result = query_orders("повернення")
    print("[TOOL_CALL_RESULT] query_orders('повернення') ->")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()

    for order_id in ["A-1001", "A-1002", "A-9999"]:
        print(f"[TOOL_CALL_RESULT] check_return_policy('{order_id}') -> {check_return_policy(order_id)}")
