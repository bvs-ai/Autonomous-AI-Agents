"""Ті самі query_orders / check_return_policy, але як інструменти LangChain.

@tool -- ім'я береться з імені функції, description -- з docstring, JSON Schema --
з type hints (єдине джерело правди, як і в 016 лекції 1, тільки тепер явно видно
результат: tool.name / tool.description / tool.args).

Для check_return_policy аргумент повинен пройти той самий pattern-контракт, що і в
002 -- це неможливо виразити самими type hints, тому тут @tool(args_schema=...)
з Pydantic-моделлю з 002.
"""

from datetime import date, timedelta

from langchain_core.tools import tool
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


@tool
def query_orders(status: str) -> list[dict]:
    """Отримати список замовлень із заданим статусом ('повернення' або 'доставлено').

    Args:
        status: Статус замовлення українською.
    """
    return [o for o in ORDERS if o["status"] == status]


class CheckReturnPolicyArgs(BaseModel):
    """Аргументи для перевірки вікна повернення."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^A-\d{4}$", description="Ідентифікатор замовлення, напр. 'A-1001'")


@tool(args_schema=CheckReturnPolicyArgs)
def check_return_policy(order_id: str) -> dict:
    """Перевірити, чи можна ще повернути замовлення за його ідентифікатором."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= RETURN_WINDOW_DAYS}


if __name__ == "__main__":
    for t in (query_orders, check_return_policy):
        print(f"[TOOL] name={t.name!r}")
        print(f"       description={t.description!r}")
        print(f"       args={t.args}\n")

    print("[INVOKE] query_orders(status='повернення') ->")
    print(" ", query_orders.invoke({"status": "повернення"}))

    print("[INVOKE] check_return_policy(order_id='A-1001') ->")
    print(" ", check_return_policy.invoke({"order_id": "A-1001"}))

    # args_schema працює одразу у два боки: це і контракт для LLM (звідки береться
    # JSON Schema інструмента), і рантайм-фільтр -- тіло функції навіть не почнеться,
    # якщо аргументи не пройшли pattern. Один опис, дві ролі.
    print("\n[INVOKE] check_return_policy(order_id='1001') ->")
    try:
        check_return_policy.invoke({"order_id": "1001"})
    except ValidationError as error:
        print(f"  ValidationError ще ДО виконання тіла: {error.errors()[0]['msg']}")
