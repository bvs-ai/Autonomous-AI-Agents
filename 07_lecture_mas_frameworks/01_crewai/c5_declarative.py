"""ОПЦІЙНО (CrewAI). Той самий пайплайн, але команда описана декларативно.

`c2_pipeline.py` збирає агентів і задачі кодом. Тут той самий склад команди
лежить у `c5_crew.json`, а Python-код лише збирає з нього об'єкти. Різниця не
косметична: конфіг можна редагувати без програміста, версіонувати окремо від
коду й тримати кілька варіантів під різні мови чи ринки.

Так само влаштований штатний спосіб CrewAI — YAML-файли `agents.yaml` і
`tasks.yaml` разом із декоратором `@CrewBase`. Ми беремо JSON і збираємо
руками, щоб було видно, що саме відбувається: жодної магії, звичайний словник
роз'їжджається по конструкторах `Agent(...)` і `Task(...)`.

Дві речі, на які варто подивитись у конфізі:

* `"tools": ["get_payments"]` — у JSON лежить лише ІМ'Я. Сам інструмент —
  це Python-функція, підставити її може тільки код (реєстр TOOLS нижче).
* `{ticket}` у description — плейсхолдер. CrewAI підставляє туди значення
  з `kickoff(inputs={...})`: конфіг залишається однаковим для будь-якого тікета.

Запуск:  .venv/bin/python 01_crewai/c5_declarative.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool

import trace_llm
from common import MODEL, TICKET, Metrics, banner
from common import get_payments as _get_payments
from common import refund as _refund


# ── Реєстр інструментів: єдине, що НЕ можна описати конфігом ────────────────
@tool("Get Payments")
def get_payments(customer_id: str) -> str:
    """Повертає список платежів клієнта за останні місяці."""
    return _get_payments(customer_id)


@tool("Refund")
def refund(payment_id: str) -> str:
    """Оформлює повернення коштів за вказаним платежем."""
    return _refund(payment_id)


TOOLS = {"get_payments": get_payments, "refund": refund}


# ── Складання команди з конфігу ─────────────────────────────────────────────
def build_crew(config: dict) -> tuple[Crew, dict[str, Task]]:
    """Перетворює словник із JSON на об'єкти CrewAI. Увесь «фреймворк» тут."""
    agents = {
        name: Agent(
            role=spec["role"],
            goal=spec["goal"],
            backstory=spec["backstory"],
            tools=[TOOLS[t] for t in spec.get("tools", [])],
            llm=LLM(model=f"gemini/{MODEL}"),  # свій екземпляр на агента — інакше метрики подвояться
            verbose=False,
            allow_delegation=False,
            max_iter=5,
        )
        for name, spec in config["agents"].items()
    }

    tasks: dict[str, Task] = {}
    for name, spec in config["tasks"].items():
        tasks[name] = Task(
            description=spec["description"],
            expected_output=spec["expected_output"],
            agent=agents[spec["agent"]],
            # context — посилання на вже створені задачі за іменем із конфігу
            context=[tasks[c] for c in spec.get("context", [])],
        )

    crew = Crew(
        agents=list(agents.values()),
        tasks=list(tasks.values()),  # порядок задач = порядок ключів у JSON
        process=Process.sequential,
        verbose=False,
    )
    return crew, tasks


if __name__ == "__main__":
    banner(
        "CrewAI",
        "Опційно — декларативний опис",
        "склад команди й задачі живуть у c5_crew.json, код лише збирає об'єкти",
    )

    # Розкоментуйте, щоб побачити головне: промпт, зібраний із JSON, — точно
    # такий самий, як на кроці 2, і {ticket} у ньому вже підставлений.
    # trace_llm.on()

    config = json.loads((Path(__file__).parent / "c5_crew.json").read_text(encoding="utf-8"))
    print("\nЗ конфігу зчитано:")
    print("  агенти :", ", ".join(config["agents"]))
    print("  задачі :", " → ".join(config["tasks"]))

    crew, tasks = build_crew(config)

    # inputs підставляються у плейсхолдери {ticket} всередині description.
    result = crew.kickoff(inputs={"ticket": TICKET})

    print("\n\n--- Проміжний результат (задача investigate) ---")
    print(tasks["investigate"].output.raw)

    print("\n--- Фінальна відповідь ---")
    print(result.raw)

    usage = crew.usage_metrics
    m = Metrics(
        framework="CrewAI",
        step="Опційно — конфіг замість коду",
        calls=usage.successful_requests,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        notes=[
            "цифри такі самі, як на кроці 2: змінилась форма опису, а не механіка",
            "штатний спосіб CrewAI — YAML + @CrewBase; тут те саме, але без магії",
        ],
    )
    m.report()
