"""КРОК 2 (CrewAI). Двоє послідовно: як саме течуть дані між агентами.

Перший агент (беремо готового з c1_agent.py) розбирається у скарзі.
Другий оформлює повернення коштів.

Питання кроку одне: **що саме другий агент отримує від першого?**
Відповідь у CrewAI — `Task.context`: текст результату першої задачі
дослівно підклеюється у промпт другої. Ніякої спільної пам'яті, ніякого
обміну об'єктами — лише рядок, який поїхав у наступний запит до LLM.

Демо друкує цей рядок. Побачивши його, легко зрозуміти дві речі:
чому пайплайн ламається, коли перший агент відповів розпливчасто,
і чому за кожну передачу ми платимо токенами.

Запуск:  .venv/bin/python 01_crewai/c2_pipeline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c1_agent import investigate, new_llm, support_agent
from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

import trace_llm
from common import Metrics, banner
from common import refund as _refund


@tool("Refund")
def refund(payment_id: str) -> str:
    """Оформлює повернення коштів за вказаним платежем."""
    return _refund(payment_id)


# ── Другий агент ────────────────────────────────────────────────────────────
# Роль вужча за першу: він не розслідує, він виконує. Розділення ролей тут не
# заради красивої метафори — воно звужує набір інструментів кожного агента.
refund_agent = Agent(
    role="Оператор повернень",
    goal="Оформити повернення саме за тим платежем, який визнано зайвим",
    backstory=(
        "Ти оформлюєш повернення за висновком колеги з підтримки. "
        "Ти повертаєш кошти рівно за один платіж — той, що визнаний дублем."
    ),
    tools=[refund],
    llm=new_llm(),  # свій екземпляр моделі — інакше метрики порахують виклики двічі
    verbose=False,
    allow_delegation=False,
    max_iter=5,
)

# ── Друга задача: context — це і є канал передачі даних ─────────────────────
# context=[investigate] означає: візьми текстовий результат задачі investigate
# і встав його у промпт цієї задачі. Це весь механізм передачі.
do_refund = Task(
    description=(
        "За висновком колеги оформи повернення коштів. "
        "Якщо дубль не підтверджено — нічого не повертай і поясни чому."
    ),
    expected_output="Один рядок українською: за яким платежем оформлено повернення.",
    agent=refund_agent,
    context=[investigate],
)


if __name__ == "__main__":
    banner(
        "CrewAI",
        "Крок 2 — двоє послідовно",
        "дані між агентами течуть як текст у Task.context",
    )

    # Трейс вимикається одним рядком: закоментуйте його — і вивід стане звичайним.
    # trace_llm.on()

    crew = Crew(
        agents=[support_agent, refund_agent],
        tasks=[investigate, do_refund],
        process=Process.sequential,  # порядок задач фіксований нами, не моделлю
        verbose=False,
    )
    result = crew.kickoff()

    print("\n\n--- Що передав перший агент (саме цей текст пішов у промпт другого) ---")
    print(investigate.output.raw)

    print("\n--- Відповідь другого агента ---")
    print(result.raw)

    usage = crew.usage_metrics
    m = Metrics(
        framework="CrewAI",
        step="Крок 2 — послідовний пайплайн",
        calls=usage.successful_requests,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        notes=[
            "маршрут задано нами: жодного виклику LLM на вибір, хто працює наступним",
            "текст першої задачі оплачується вдруге — як частина промпту другої",
        ],
    )
    m.report()
