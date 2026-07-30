"""Retry -- не універсальні ліки. Повторювати варто лише те, що МОЖЕ минути саме:
перевантаження, тимчасова недоступність, мережевий таймаут.

  повторюємо:    429 Too Many Requests, 503 Service Unavailable, таймаут, обрив зʼєднання
  НЕ повторюємо: 400 Bad Request, 401 Unauthorized, 403, 404 Not Found,
                 будь-яка ValidationError від Pydantic

Чому це важливо саме для агента: три повтори 404-ї -- це три затримки backoff і
втрачені секунди, після яких модель усе одно отримає ту саму відповідь. Гірше
того, на не-ідемпотентних операціях (списання коштів) повтор -- це вже не марна
робота, а подвійний платіж.

Той самий tool_wrapper, що і в 008, але тепер він розрізняє два класи помилок.

Запуск:  python 009_retry_policy_what_not_to_retry.py
"""

import functools
import logging
from collections.abc import Callable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("agent.tools")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class NonRetryableToolError(Exception):
    """Помилка, яку немає сенсу повторювати: контракт/права/відсутність ресурсу."""


class OrdersAPI:
    """Симуляція API замовлень: відповідь залежить від запиту, а не від спроби."""

    def __init__(self):
        self.calls = 0

    def get_order(self, order_id: str, status_code: int) -> dict:
        self.calls += 1
        if status_code in RETRYABLE_STATUS:
            raise httpx.HTTPStatusError(
                f"{status_code} тимчасова відмова", request=None, response=None
            )
        if status_code >= 400:
            raise NonRetryableToolError(f"{status_code} для {order_id}: повторювати немає сенсу")
        return {"id": order_id, "delivered_at": "2026-07-26"}


api = OrdersAPI()


def tool_wrapper(max_attempts: int = 3) -> Callable:
    """Ключовий рядок -- retry_if_exception_type: він і є політикою повторів."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            @retry(
                stop=stop_after_attempt(max_attempts),
                wait=wait_fixed(0.1),  # у демо -- коротко, у проді -- exponential+jitter (008)
                retry=retry_if_exception_type(httpx.HTTPStatusError),
                reraise=True,
            )
            def call_with_retry():
                return func(*args, **kwargs)

            try:
                return call_with_retry()
            except httpx.HTTPStatusError as error:
                return {"error": str(error), "retryable": True}
            except NonRetryableToolError as error:
                # Сюди потрапляємо з ПЕРШОЇ ж спроби: tenacity навіть не почала повтори,
                # бо цей тип винятку не входить у retry_if_exception_type.
                return {"error": str(error), "retryable": False}

        return wrapped

    return decorator


@tool_wrapper(max_attempts=3)
def fetch_order(order_id: str, status_code: int) -> dict:
    return api.get_order(order_id, status_code)


if __name__ == "__main__":
    scenarios = [
        (503, "сервіс перевантажений -- варто повторити"),
        (404, "замовлення не існує -- повторювати нічого"),
        (401, "протух токен -- повтори лише спалять час"),
    ]

    for status_code, comment in scenarios:
        api.calls = 0
        result = fetch_order("A-1001", status_code)
        print(f"[{status_code}] {comment}")
        print(f"    звернень до API: {api.calls}")
        print(f"    результат: {result}\n")

    print("Різниця у витратах видна саме по кількості звернень: 3 проти 1.")
