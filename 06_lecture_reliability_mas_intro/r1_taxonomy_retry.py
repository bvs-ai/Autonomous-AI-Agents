"""r1 — таксономія помилок і bounded retry.

  python r1_taxonomy_retry.py naive       # ретраїмо все підряд -> спалений бюджет
  python r1_taxonomy_retry.py tenacity    # @retry тільки на TransientError
  python r1_taxonomy_retry.py permanent   # 404: жодного повтору, миттєва відмова

Зовнішній API — детермінована заглушка: два перші виклики віддають 503,
третій 200. Мережі і LLM немає, вивід однаковий на кожному запуску
(крім jitter у паузах — це і є суть демо).
"""
import sys
import time

from tenacity import (before_sleep_log, retry, retry_if_exception_type,
                      stop_after_attempt, wait_exponential_jitter)
import logging

CONTEXT_TOKENS = 4_000      # кожна спроба тягне повний контекст діалогу в LLM
spent_tokens = 0


class TransientError(Exception):
    """Розсмокчеться саме. Повтор має сенс — але лише для ідемпотентної операції."""


class PermanentError(Exception):
    """Не розсмокчеться. Десята спроба дасть той самий результат."""


TRANSIENT = {
    503,  # Service Unavailable — сервер перевантажений, сам просить прийти пізніше
    429,  # Too Many Requests — рейт-ліміт; 4xx, але саме заради нього retry й існує
    502,  # Bad Gateway — проміжний вузол не достукався до бекенда
    504,  # Gateway Timeout — бекенд міг встигнути списати гроші: повтор лише з idempotency key
    # сюди ж клієнтський таймаут і обрив з'єднання: HTTP-коду немає, наслідок той самий
}

PERMANENT = {
    404,  # Not Found — ресурсу немає, чекати нема чого
    400,  # Bad Request — невалідний запит (у власному FastAPI те саме прилетить як 422)
    501,  # Not Implemented — 5xx, але метод не з'явиться й за годину
}


def classify_http_error(status: int) -> Exception:
    """Класифікатор працює ДО retry-логіки: тип помилки задає стратегію."""
    if status in TRANSIENT:
        return TransientError(f"HTTP {status} — тимчасовий збій")
    return PermanentError(f"HTTP {status} — постійна помилка")


_calls = 0


def charge_api(fail_status: int = 503, fail_times: int = 2) -> dict:
    """Заглушка платіжного API. Кожен виклик 'коштує' повний контекст."""
    global _calls, spent_tokens
    _calls += 1
    spent_tokens += CONTEXT_TOKENS
    print(f"    [api] виклик #{_calls}, спалено токенів: {spent_tokens}")
    error = classify_http_error(fail_status)
    if isinstance(error, TransientError) and _calls > fail_times:
        return {"status": "ok", "payment_id": "pay-7781"}
    # тільки транзієнтна помилка «розсмоктується»: 404 буде 404 і на десятій спробі
    raise error


# --- 1. Наївний ретрай: except Exception + фіксована пауза -------------------

def naive_call(fail_status: int) -> dict:
    for attempt in range(1, 4):
        try:
            return charge_api(fail_status)
        except Exception as e:                     # <-- ловимо ВСЕ
            print(f"    [naive] спроба {attempt} впала: {e}")
            time.sleep(0.5)                        # <-- фіксована пауза, без jitter
    raise RuntimeError("вичерпано спроби")


# --- 2. tenacity: політика окремо від бізнес-логіки --------------------------

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="    [tenacity] %(message)s")
log = logging.getLogger("retry")


@retry(
    retry=retry_if_exception_type(TransientError),   # ТІЛЬКИ транзієнтні
    stop=stop_after_attempt(3),                      # завжди обмежений
    wait=wait_exponential_jitter(initial=0.4, max=5),  # backoff + jitter
    before_sleep=before_sleep_log(log, logging.INFO),
    reraise=True,
)
def resilient_call(fail_status: int) -> dict:
    return charge_api(fail_status)


mode = (sys.argv[1:] or ["tenacity"])[0]
t0 = time.monotonic()

if mode == "naive":
    print("[naive] ретраїмо будь-який Exception, пауза фіксована 0.5s")
    print("        404 (постійна помилка) теж буде повторено — так горить бюджет:")
    try:
        naive_call(fail_status=404)
    except RuntimeError as e:
        print(f"[naive] підсумок: {e}, спалено {spent_tokens} токенів на безнадійних повторах")

elif mode == "tenacity":
    print("[tenacity] TransientError -> 3 спроби з експоненційним backoff + jitter")
    result = resilient_call(fail_status=503)
    print(f"[tenacity] успіх: {result}, спроб: {_calls}, токенів: {spent_tokens}")

elif mode == "permanent":
    print("[tenacity] той самий декоратор, але API віддає 404")
    try:
        resilient_call(fail_status=404)
    except PermanentError as e:
        print(f"[tenacity] fail-fast: {e}")
        print(f"[tenacity] спроб: {_calls}, токенів: {spent_tokens} — жодного зайвого повтору")

print(f"[час] {time.monotonic() - t0:.2f}s")
