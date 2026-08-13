"""r5 — circuit breaker: fail-fast замість каскаду безнадійних ретраїв.

  python r5_circuit_breaker.py off       # тільки retry: довбимо мертвий сервіс
  python r5_circuit_breaker.py on        # retry + breaker: CLOSED -> OPEN -> HALF_OPEN
  python r5_circuit_breaker.py taxonomy  # валідаційна помилка НЕ відкриває circuit

Сервіс «реєстр контрагентів» лежить перші 2.5 секунди, далі оживає.
Агент робить 14 перевірок поспіль. Порівнюємо ціну: спроби, токени, час.
"""
import asyncio
import sys
import time


class TransientError(Exception):
    """Нестабільність сервісу: таймаут, 5xx, 429."""


class PermanentError(Exception):
    """Невалідний аргумент/бізнес-помилка. Про здоровʼя сервісу не говорить."""


class CircuitOpenError(Exception):
    """Виклик навіть не зроблено: circuit відкритий."""


class CircuitBreaker:
    """Три стани і два лічильники — більше в circuit breaker нічого немає.

    CLOSED    — пропускаємо все, рахуємо збої поспіль.
    OPEN      — не пропускаємо нічого, поки не мине cooldown.
    HALF_OPEN — пропускаємо одну пробу: ожив сервіс чи ні.

    Тут виклики послідовні. У проді додається asyncio.Lock навколо стану
    і прапорець «проба вже в польоті», щоб у HALF_OPEN пройшов РІВНО один
    виклик, а не всі, що чекали на cooldown.
    """

    def __init__(self, failure_threshold=3, cooldown=1.0):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.state = "CLOSED"
        self.failures = 0
        self.opened_at = 0.0

    def before(self) -> None:
        """Викликати ПЕРЕД зверненням до сервісу. OPEN -> виклику не буде."""
        if self.state == "OPEN":
            # time.monotonic(), а не time.time(): не зʼїде від переводу годинника
            if time.monotonic() - self.opened_at < self.cooldown:
                raise CircuitOpenError("circuit OPEN — виклик не робимо")
            self.state = "HALF_OPEN"
            print("      [breaker] cooldown минув -> HALF_OPEN")

    def on_success(self) -> None:
        if self.state != "CLOSED":
            print("      [breaker] проба успішна -> CLOSED")
        self.state = "CLOSED"
        self.failures = 0

    def on_failure(self) -> None:
        self.failures += 1
        # провалена проба в HALF_OPEN відкриває circuit одразу, без лічильника
        if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = time.monotonic()
            print(f"      [breaker] {self.failures} збоїв поспіль -> OPEN "
                  f"на {self.cooldown}s")


# --- сервіс і облік витрат ---------------------------------------------------

TOKENS_PER_ATTEMPT = 4_000
stats = {"attempts": 0, "tokens": 0}
T0 = time.monotonic()
RECOVERS_AT = 2.5


async def registry_lookup(edrpou: str) -> dict:
    stats["attempts"] += 1
    stats["tokens"] += TOKENS_PER_ATTEMPT
    if edrpou == "невалідний":
        raise PermanentError("ЄДРПОУ має бути 8 цифр")
    await asyncio.sleep(0.25)                      # «повільно вмираючий» сервіс
    if time.monotonic() - T0 < RECOVERS_AT:
        raise TransientError("registry: 503")
    return {"edrpou": edrpou, "status": "active"}


async def call_with_retry(edrpou: str, breaker: CircuitBreaker | None) -> str:
    """Bounded retry: рівно дві спроби. Breaker стоїть НАД retry."""
    if breaker:
        breaker.before()                           # OPEN -> CircuitOpenError
    try:
        result = await registry_lookup(edrpou)
    except TransientError:
        await asyncio.sleep(0.1)
        try:
            result = await registry_lookup(edrpou)
        except TransientError:
            if breaker:
                breaker.on_failure()               # серія збоїв -> справа breaker'а
            raise
    if breaker:
        breaker.on_success()
    return f"ok {result['status']}"


# --- сценарії ----------------------------------------------------------------

async def demo_taxonomy(breaker: CircuitBreaker) -> None:
    """PermanentError не свідчить про перевантаження — circuit лишається CLOSED."""
    print("[taxonomy] валідаційна помилка не свідчить про перевантаження сервісу")
    for i in range(1, 5):
        try:
            await call_with_retry("невалідний", breaker)
        except PermanentError as e:
            print(f"  виклик {i}: PermanentError({e}) -> circuit {breaker.state}, "
                  f"збоїв: {breaker.failures}")
    print("[taxonomy] circuit лишився CLOSED: breaker реагує ТІЛЬКИ на TransientError")


async def demo_load(breaker: CircuitBreaker | None) -> None:
    """14 перевірок поспіль по мертвому сервісу. Рахуємо ціну."""
    print(f"[режим] {'retry + circuit breaker' if breaker else 'тільки retry'}\n")
    for i in range(1, 15):
        t = time.monotonic() - T0
        try:
            res = await call_with_retry("12345678", breaker)
            print(f"  {t:5.2f}s виклик {i:2}: {res}")
        except CircuitOpenError as e:
            print(f"  {t:5.2f}s виклик {i:2}: fail-fast ({e}) -> кешований fallback, 0 токенів")
        except TransientError:
            print(f"  {t:5.2f}s виклик {i:2}: провал після 2 спроб")
        await asyncio.sleep(0.15)

    print(f"\n[ціна] спроб до сервісу: {stats['attempts']}, "
          f"токенів: {stats['tokens']}, час: {time.monotonic() - T0:.2f}s")


async def main(mode: str) -> None:
    """Три режими — три рядки. Різниця між on і off рівно одна: є breaker чи ні."""
    if mode == "taxonomy":
        await demo_taxonomy(CircuitBreaker())
    elif mode == "off":
        await demo_load(breaker=None)          # тільки retry
    else:
        await demo_load(CircuitBreaker())      # retry + breaker


if __name__ == "__main__":            # r7 імпортує звідси CircuitBreaker
    asyncio.run(main((sys.argv[1:] or ["on"])[0]))
