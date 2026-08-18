"""КРОК 2 (Google ADK). Двоє послідовно: дані течуть через session.state.

Третій фреймворк — третій механізм передачі даних, і це головне, що тут треба
побачити:

* CrewAI — текст результату попередньої задачі (`Task.context`);
* Agent Framework — уся розмова цілком;
* ADK — **іменована комірка в стані сесії**. Перший агент пише свій результат
  у `output_key="investigation"`, другий підставляє його у свою інструкцію
  як `{investigation}`.

Тобто в ADK ми точно контролюємо, що саме побачить наступний агент: не всю
історію, а рівно одне поле. Передбачуваність тут максимальна з трьох — ціною
того, що кожен зв'язок доводиться описувати руками.

`SequentialAgent` у версії 2.7 ще працює, але вже позначений `@deprecated`
на користь нового `Workflow` — його подивимося на кроці 3.

Запуск:  .venv/bin/python 03_adk/g2_pipeline.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trace_llm
from g1_agent import run, support_agent
from google.adk.agents import LlmAgent, SequentialAgent

from common import MODEL, TICKET, Metrics, banner, refund

# ── Куди пише перший агент ──────────────────────────────────────────────────
# output_key — це ключ у session.state. Одне присвоєння перетворює агента
# з «того, що просто відповів» на «того, що поклав результат у спільне поле».
support_agent.output_key = "investigation"

# ── Другий агент читає це поле у своїй інструкції ───────────────────────────
# {investigation} підставляється ADK перед викликом моделі. Якщо ключа
# в state немає — буде помилка, і це добре: зв'язок явний, а не «на удачу».
refund_agent = LlmAgent(
    name="refund_operator",
    model=MODEL,
    description="Оформлює повернення коштів",
    instruction=(
        "Ти оформлюєш повернення за висновком колеги з підтримки.\n\n"
        "Висновок колеги:\n{investigation}\n\n"
        "Поверни рівно один платіж — той, що визнаний дублем. Якщо дубль "
        "не підтверджено, нічого не повертай і поясни чому. "
        "Відповідай українською одним рядком."
    ),
    tools=[refund],
)

# ── Пайплайн ────────────────────────────────────────────────────────────────
# SequentialAgent — не «розумний» координатор, а звичайний цикл по списку.
# Жодного виклику LLM на вибір, хто працює наступним, тут немає.
pipeline = SequentialAgent(
    name="billing_pipeline",
    sub_agents=[support_agent, refund_agent],
)


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()

    banner(
        "Google ADK",
        "Крок 2 — двоє послідовно",
        "дані течуть через іменоване поле session.state",
    )

    metrics = Metrics(framework="ADK", step="Крок 2 — послідовний пайплайн")
    await run(pipeline, TICKET, metrics, session_id="g2")

    metrics.notes = [
        "маршрут заданий нами: на координацію не витрачено жодного виклику",
        "другий агент бачить рівно одне поле state, а не всю історію розмови",
        "SequentialAgent у 2.x позначений @deprecated — заміну дивимось на кроці 3",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
