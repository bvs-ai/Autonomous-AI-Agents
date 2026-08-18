"""КРОК 2 (Microsoft Agent Framework). Двоє послідовно: як течуть дані.

Те саме завдання, що й у `01_crewai/c2_pipeline.py`, — і тут головна різниця
двох фреймворків.

CrewAI передає далі **текст результату** попередньої задачі (`Task.context`).
MAF передає далі **всю розмову**: список повідомлень, до якого кожен учасник
дописує свої. Другий агент бачить не переказ, а оригінальні репліки й виклики
інструментів першого.

Ціна теж різна: спільна розмова означає, що промпт росте з кожним учасником.
Демо друкує ланцюжок повідомлень цілком — саме його ми й оплачуємо токенами.

Запуск:  .venv/bin/python 02_msagent/m2_pipeline.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_framework.orchestrations import SequentialBuilder
from m1_agent import client, last_request, metrics, support_agent

from common import TICKET, banner, refund

import trace_llm

# Щоб побачити кожен запит до моделі цілком:
#     trace_llm.on()

# ── Другий агент: той самий клієнт, інша інструкція ─────────────────────────
# Клієнт моделі перевикористовуємо — разом із ним і наше middleware-лічильник.
refund_agent = client.as_agent(
    name="refund_operator",
    middleware=[trace_llm.whoami],
    instructions=(
        "Ти оформлюєш повернення коштів за висновком колеги з підтримки. "
        "Повертай рівно один платіж — той, що визнаний дублем. "
        "Якщо дубль не підтверджено, нічого не повертай і поясни чому. "
        "Відповідай українською одним рядком."
    ),
    tools=[refund],
)

# ── Пайплайн ────────────────────────────────────────────────────────────────
# Порядок задаємо ми, а не модель: спочатку підтримка, потім повернення.
# Жодного виклику LLM на вибір маршруту тут немає.
workflow = SequentialBuilder(participants=[support_agent, refund_agent]).build()


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()
    
    banner(
        "Microsoft Agent Framework",
        "Крок 2 — двоє послідовно",
        "далі їде вся розмова, а не переказ результату",
    )

    metrics.step = "Крок 2 — послідовний пайплайн"
    result = await workflow.run(TICKET)

    # last_request — це рівно ті повідомлення, які middleware бачив в останньому
    # зверненні до моделі, тобто промпт другого агента. Не переказ, а факт.
    print("\n\n\n--------- Останній запит до моделі: усе, що бачив другий агент ---")
    for message in last_request:
        author = message.author_name or str(message.role)
        print(f"[{author}] {message.text or '(виклик інструмента)'}")

    print("\n--- Відповідь другого агента ---")
    print(result.get_outputs()[-1].text)

    metrics.notes = [
        "маршрут заданий нами: на координацію не витрачено жодного виклику",
        "промпт другого агента містить усі повідомлення першого — звідси зростання токенів",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
