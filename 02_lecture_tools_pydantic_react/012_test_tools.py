"""Тестування інструментів: unit-тести Pydantic-валідації без жодних моків,
мок зовнішнього виклику в місці використання, ізоляція мережі через
httpx.MockTransport, і тест retry-логіки без реальних затримок.

Запуск:  pytest 012_test_tools.py -v
"""

from datetime import date
from typing import Literal
from unittest.mock import patch

import httpx
import pytest
import tenacity
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from stop_controller import StopController


# ---------------------------------------------------------------------------
# 1) Unit-тест вхідного контракту Pydantic -- без зовнішніх викликів.
#    Детерміновано, ловить помилки ДО того, як дійде до HTTP/БД.
# ---------------------------------------------------------------------------
class SearchOrdersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["повернення", "доставлено"]
    order_id: str = Field(pattern=r"^A-\d{4}$")
    checked_at: date

    @model_validator(mode="after")
    def _checks(self):
        if self.checked_at < date(2020, 1, 1):
            raise ValueError("Дата перевірки не може бути настільки старою")
        return self


def test_rejects_extra_field():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SearchOrdersInput(
            status="повернення", order_id="A-1001", checked_at="2026-01-01", priority="high"
        )


def test_rejects_bad_order_id_pattern():
    with pytest.raises(ValidationError, match="pattern"):
        SearchOrdersInput(status="повернення", order_id="1001", checked_at="2026-01-01")


def test_accepts_valid_payload():
    parsed = SearchOrdersInput(status="повернення", order_id="A-1001", checked_at="2026-01-01")
    assert parsed.order_id == "A-1001"


# ---------------------------------------------------------------------------
# 2) Мок зовнішнього виклику -- патчити в МІСЦІ ВИКОРИСТАННЯ, не глобально.
#    Якби tools/orders.py робив `import httpx` і викликав httpx.get(...),
#    патчити треба tools.orders.httpx.get (рядком, за назвою модуля), а не
#    httpx.get напряму. Тут увесь "модуль" -- цей самий файл; але через
#    цифру на початку імені ("012_test_tools") рядкове ім'я модуля невалідне
#    для patch(), тому використовуємо patch.object(httpx, "get") --
#    той самий принцип "патч у місці використання", але за посиланням на обʼєкт.
# ---------------------------------------------------------------------------
def call_orders_api(order_id: str) -> dict:
    response = httpx.get(f"https://api.orders.internal/v1/orders/{order_id}")
    response.raise_for_status()
    return response.json()


def test_call_orders_api_timeout_then_success():
    with patch.object(httpx, "get") as mock_get:
        mock_get.side_effect = [
            httpx.TimeoutException("timeout"),
            type(
                "Response", (), {"json": lambda self: {"id": "A-1001", "delivered_days_ago": 3},
                                  "raise_for_status": lambda self: None}
            )(),
        ]
        with pytest.raises(httpx.TimeoutException):
            call_orders_api("A-1001")  # перша спроба (без retry в цій функції) падає

        result = call_orders_api("A-1001")  # друга спроба -- вже успіх
        assert result["id"] == "A-1001"
        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# 3) httpx.MockTransport -- ізоляція мережі власним обробником запитів,
#    без патчингу конкретного клієнта.
# ---------------------------------------------------------------------------
def make_orders_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/orders/A-1001":
            return httpx.Response(200, json={"id": "A-1001", "delivered_days_ago": 3})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.orders.internal")


def test_httpx_mocktransport_found():
    client = make_orders_client()
    response = client.get("/v1/orders/A-1001")
    response.raise_for_status()
    assert response.json()["delivered_days_ago"] == 3


def test_httpx_mocktransport_not_found():
    client = make_orders_client()
    response = client.get("/v1/orders/A-9999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4) Тест retry-логіки без реальних затримок: monkeypatch tenacity.nap.sleep.
#    За замовчуванням (без reraise=True) tenacity після вичерпання спроб НЕ
#    повертає {"error": ...} і НЕ мовчить -- вона підіймає tenacity.RetryError,
#    що обгортає останній виняток. Це і є типова помилка в ДЗ: забути
#    reraise=True/обробку RetryError і отримати необроблений RetryError
#    там, де очікували вихідний httpx.TimeoutException.
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def flaky_call():
    raise httpx.TimeoutException("сервіс замовлень недоступний")


def test_tenacity_raises_retry_error_by_default(monkeypatch):
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)  # прибрати реальні затримки
    with pytest.raises(tenacity.RetryError) as exc_info:
        flaky_call()
    # Оригінальний виняток нікуди не зникає -- він доступний через __cause__.
    assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)
def flaky_call_reraise():
    raise httpx.TimeoutException("сервіс замовлень недоступний")


def test_tenacity_reraise_true_gives_original_exception(monkeypatch):
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)
    with pytest.raises(httpx.TimeoutException):
        flaky_call_reraise()


# ---------------------------------------------------------------------------
# 5) Стоп-критерії -- це звичайний код, і тестується він без жодного LLM.
#    Саме тому StopController винесений в окремий модуль (stop_controller.py):
#    логіку зупинки агента можна покрити тестами, а поведінку моделі -- ні.
# ---------------------------------------------------------------------------
def test_loop_detection_fires_on_third_identical_call():
    controller = StopController(max_steps=10, max_repeats=3)
    call = ["query_orders:{'status': 'скасовано'}"]

    assert controller.should_stop(1, 100, call)[0] is False
    assert controller.should_stop(2, 200, call)[0] is False

    stop, reason = controller.should_stop(3, 300, call)
    assert stop is True
    assert "Зациклювання" in reason


def test_different_calls_do_not_trigger_loop_detection():
    controller = StopController(max_steps=10, max_repeats=3)

    for step, name in enumerate(["query_orders:{}", "check_return_policy:{}", "query_orders:{}"], start=1):
        stop, _ = controller.should_stop(step, 100, [name])
        assert stop is False


def test_token_budget_stops_even_when_steps_are_few():
    controller = StopController(max_steps=100, max_tokens=5_000)

    stop, reason = controller.should_stop(step=2, tokens=5_001, tool_calls=[])
    assert stop is True
    assert "бюджет токенів" in reason
