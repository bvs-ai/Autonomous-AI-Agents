"""Production-обвязка навколо check_return_policy: тайм-аути, retry з backoff+jitter,
логування, graceful degradation -- «інструмент без обвʼязки, як автомобіль без ременів».

Сценарій: check_return_policy більше не читає локальний список ORDERS напряму, а
«ходить» у зовнішній сервіс замовлень (симуляція через FlakyOrderService: перші
два виклики падають по read-таймауту, третій -- вдалий).

Три речі, які тут варто побачити:
  1. тайм-аут задається ПОКОМПОНЕНТНО (connect/read/write/pool), а timeout=None --
     антипатерн: один повільний сервіс підвішує весь агентний цикл;
  2. wait_exponential знижує навантаження на сервіс, що вже лежить, а wait_random
     (jitter) розводить у часі тисячу агентів, які інакше повторять синхронно
     (thundering herd);
  3. після вичерпання спроб інструмент повертає СТРУКТУРОВАНУ помилку, а не падає:
     модель отримає її як Observation і зможе піти іншим шляхом.

Запуск:  python 008_tool_wrapper_timeouts_retries.py
"""

import functools
import logging
import time
from collections.abc import Callable
from datetime import date, timedelta

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("agent.tools")

RETURN_WINDOW_DAYS = 30

# Покомпонентний тайм-аут: «повільно» на різних етапах означає різні проблеми.
# Орієнтири з лекції: connect 2-5с, read 5-30с, write 5-10с, pool 1-5с.
ORDERS_API_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=2.0)


class FlakyOrderService:
    """Симуляція зовнішнього сервісу замовлень: перші N викликів -- read-таймаут."""

    def __init__(self, fail_times: int = 2):
        self.fail_times = fail_times
        self.attempts = 0

    def get_order(self, order_id: str, timeout: httpx.Timeout = ORDERS_API_TIMEOUT) -> dict:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise httpx.TimeoutException(f"спроба {self.attempts}: read timeout > {timeout.read}s")

        return {"id": order_id, "delivered_at": (date.today() - timedelta(days=3)).isoformat()}


def tool_wrapper(max_attempts: int = 3, retry_on: tuple = (httpx.TimeoutException,)) -> Callable:
    """Декоратор: retry з backoff+jitter, логування спроб, graceful degradation."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)  # без цього LangChain/агент загубить name/__doc__ інструмента
        def wrapped(*args, **kwargs):
            @retry(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1),
                retry=retry_if_exception_type(retry_on),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            def call_with_retry():
                return func(*args, **kwargs)

            start = time.time()
            try:
                result = call_with_retry()
                logger.info(f"[OK] {func.__name__} за {time.time() - start:.2f}s")
                return result
            except retry_on as error:
                # reraise=True означає: після вичерпання спроб tenacity підіймає
                # ОРИГІНАЛЬНИЙ виняток, а не tenacity.RetryError. Тому ловимо саме
                # retry_on (без reraise тут був би RetryError -- див. 012_test_tools.py).
                logger.error(f"[FAIL] {func.__name__}: {error}")
                return {
                    "error": f"Сервіс замовлень недоступний після {max_attempts} спроб",
                    "retryable": True,  # моделі корисно знати, що спробувати пізніше має сенс
                }

        return wrapped

    return decorator


order_service = FlakyOrderService(fail_times=2)
down_service = FlakyOrderService(fail_times=999)  # сервіс, що не підніметься взагалі


@tool_wrapper(max_attempts=3)
def check_return_policy(order_id: str) -> dict:
    """Перевіряє, чи можна ще повернути замовлення (звертається до зовнішнього сервісу)."""
    order = order_service.get_order(order_id)
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= RETURN_WINDOW_DAYS}


@tool_wrapper(max_attempts=3)
def check_return_policy_down(order_id: str) -> dict:
    """Той самий інструмент, але зовнішній сервіс лежить постійно."""
    order = down_service.get_order(order_id)
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= RETURN_WINDOW_DAYS}


if __name__ == "__main__":
    print(f"[TIMEOUT] {ORDERS_API_TIMEOUT}\n")

    print("--- сервіс оживає з третьої спроби ---")
    print(f"[TOOL_CALL_RESULT] {check_return_policy(order_id='A-1001')}\n")

    print("--- сервіс лежить: спроби вичерпані, але агент не падає ---")
    print(f"[TOOL_CALL_RESULT] {check_return_policy_down(order_id='A-1002')}")
