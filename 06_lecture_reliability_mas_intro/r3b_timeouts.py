"""r3b — два рівні таймаутів: на один запит і на всю операцію.

  python r3b_timeouts.py

Продовження r3 (час як третій вимір бюджету), винесене окремо: спільного коду
з графом бюджетів немає, це самостійний сюжет.

Головна теза: таймаути НЕ складаються. Локальний таймаут відповідає на питання
«чи не завис конкретний запит», а не «скільки ми вже витратили». З ретраями
тривалість операції дорівнює «спроби × (запит + пауза)» і не обмежена нічим,
доки не поставити окремий дедлайн на всю бізнес-операцію.

Мережі немає, затримки — asyncio.sleep, вивід однаковий на кожному запуску.
"""
import asyncio
import time


# Два рівні таймаутів. Локальний (на один запит) не рятує від того, що
# операція з ретраями сумарно висить довше за дедлайн бізнес-операції.

async def fetch_one(attempt: int) -> str:
    async with asyncio.timeout(0.5):          # рівень 1: один HTTP-запит
        await asyncio.sleep(0.4)              # «повільний, але не мертвий» API
        return f"відповідь #{attempt}"


async def with_retries() -> str:
    for attempt in range(1, 6):
        print(f"  [спроба {attempt}] запит із локальним таймаутом 0.5s")
        await fetch_one(attempt)
        raise_transient = attempt < 5
        if raise_transient:
            print("  [спроба] 503, повторюємо")
            await asyncio.sleep(0.2)
            continue
        return "ок"
    return "ок"


async def main() -> None:
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(1.0):      # рівень 2: уся корутина з ретраями
            await with_retries()
    except TimeoutError:                      # ловимо ПОЗА async with
        print(f"[timeout] глобальний дедлайн 1.0s спрацював на {time.monotonic() - t0:.2f}s")
        print("[timeout] локальні таймаути були цілі — жоден запит не перевищив 0.5s")
        print("[timeout] end-to-end бюджет операції — окремий рівень, а не сума таймаутів HTTPX")


asyncio.run(main())
