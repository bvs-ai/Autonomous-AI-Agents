"""КРОК 1 (Microsoft Agent Framework). Агент з інструкцією та інструментом.

Та сама задача, що й у CrewAI на кроці 1, — і одразу видно різницю підходу.
Тут немає role/goal/backstory: є клієнт моделі, з якого одним викликом
`as_agent(...)` роблять агента, і є звичайний рядок `instructions`.

Інструменти передаються голими Python-функціями з common.py — без декораторів
і без класів-обгорток: опис для моделі фреймворк збирає з сигнатури й docstring.

Ще одна відмінність, помітна з першого рядка: API асинхронний, тому всі демо
цієї гілки запускаються через asyncio.run.

Запуск:  .venv/bin/python 02_msagent/m1_agent.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_framework import ChatContext, Message
from agent_framework.gemini import GeminiChatClient

from common import MODEL, TICKET, Metrics, banner, get_payments
import trace_llm

# ── Лічильник викликів LLM ──────────────────────────────────────────────────
# У CrewAI метрики рахує сам фреймворк, тут — ні. Пишемо middleware:
# функція, крізь яку проходить кожне звернення до моделі. Це і є місце,
# де у MAF роблять логування, трейсинг і будь-який перехоплювач.
metrics = Metrics(framework="Agent Framework", step="Крок 1 — один агент")

# Останній запит, що пішов у модель. Знадобиться на кроці 2, щоб показати
# студентам не переказ, а точний список повідомлень, за який ми заплатили.
last_request: list[Message] = []


async def count_llm_calls(context: ChatContext, call_next) -> None:
    """Рахує звернення до моделі та підсумовує токени.

    Заразом лагодить дрібницю, на яку інакше наступимо на кроках 2 і 3:
    Gemini відхиляє запит, який закінчується реплікою моделі, а в багатоагентній
    розмові саме так і буває. Додаємо короткий хід «від користувача».
    Це і є сенс middleware — одне місце, де правлять усі запити до моделі.
    """
    metrics.calls += 1
    last_request[:] = context.messages
    if context.messages and str(context.messages[-1].role) == "assistant":
        context.messages.append(Message("user", ["Продовжуй за своєю інструкцією."]))
    await call_next()
    usage = getattr(context.result, "usage_details", None)
    if usage:
        metrics.prompt_tokens += usage.get("input_token_count", 0) or 0
        metrics.completion_tokens += usage.get("output_token_count", 0) or 0


# ── Клієнт і агент ──────────────────────────────────────────────────────────
# Клієнт — це «як ходити в модель», агент — «яка в нього інструкція та тули».
# Одного клієнта можна перевикористати для скількох завгодно агентів; так ми
# і зробимо на кроках 2 і 3.
client = GeminiChatClient(model=MODEL, middleware=[count_llm_calls, trace_llm.trace])

support_agent = client.as_agent(
    name="support",
    middleware=[trace_llm.whoami],
    instructions=(
        "Ти спеціаліст підтримки платіжного сервісу. "
        "Спочатку подивись виписку по платежах інструментом get_payments, "
        "і лише потім роби висновок. Відповідай українською, максимум 5 рядків."
    ),
    tools=[get_payments],
)


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()

    banner(
        "Microsoft Agent Framework",
        "Крок 1 — агент і інструкція",
        "агент = клієнт моделі + рядок instructions + звичайні функції-тули",
    )

    result = await support_agent.run(TICKET)

    print("\n\n\n----------- Відповідь агента ---")
    print(result.text)

    metrics.notes = [
        "виклики рахує не фреймворк, а наше middleware — у MAF це штатна точка входу",
        "тули пішли без обгорток: опис зібрано з сигнатури й docstring",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
