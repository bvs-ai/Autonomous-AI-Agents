"""КРОК 3 (CrewAI). Ієрархія: маршрут обирає менеджер — і за це є ціна.

На кроці 2 порядок роботи задали ми: задача 1, потім задача 2. Тут ми його
НЕ задаємо. Є відділ із трьох ролей, є одна задача — і менеджер (окремий
агент, якого CrewAI створює сам) вирішує, кого залучити й у якому порядку.

Що показуємо: це працює, але кожне рішення менеджера — це ще один виклик LLM.
Порівняйте `викликів LLM` тут і на кроці 2: різниця і є ціна координації.
Пункт «делегування» у метриках — головний висновок лекції про MAS: динамічний
вибір беруть тоді, коли маршрут заздалегідь невідомий, а не «щоб було гнучко».

Запуск:  .venv/bin/python 01_crewai/c3_hierarchical.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c1_agent import new_llm, support_agent
from c2_pipeline import refund_agent
from crewai import Agent, Crew, Process, Task

import trace_llm
from common import TICKET, Metrics, banner

# ── Третій виконавець: без інструментів, лише текст ─────────────────────────
writer_agent = Agent(
    role="Редактор клієнтських листів",
    goal="Написати клієнту коротку ввічливу відповідь простою мовою",
    backstory=(
        "Ти перекладаєш внутрішні висновки на мову клієнта: без ID транзакцій "
        "у першому рядку, без жаргону, з чітким «що буде далі»."
    ),
    llm=new_llm(),
    verbose=False,
    allow_delegation=False,
    max_iter=5,
)

# ── Задача без виконавця ────────────────────────────────────────────────────
# Ключова відмінність від кроку 2: тут немає agent=... . Кому це робити —
# вирішує менеджер під час прогону.
handle_ticket = Task(
    description=(
        "Опрацюй тікет підтримки повністю: встанови факти, за потреби оформи "
        f"повернення, підготуй відповідь клієнту.\n\nТікет:\n{TICKET}"
    ),
    expected_output=(
        "Дві частини українською: (1) лист клієнту, максимум 5 рядків; "
        "(2) рядок «Внутрішньо:» з ID платежу, за яким оформлено повернення."
    ),
)


if __name__ == "__main__":
    banner(
        "CrewAI",
        "Крок 3 — ієрархічний процес",
        "менеджер обирає виконавців сам, і кожен вибір — це виклик LLM",
    )

    # Трейс вимикається одним рядком: закоментуйте його — і вивід стане звичайним.
    # trace_llm.on()

    crew = Crew(
        agents=[support_agent, refund_agent, writer_agent],
        tasks=[handle_ticket],
        process=Process.hierarchical,
        # Менеджера CrewAI створює сам, ми даємо йому лише модель — і теж окремий
        # екземпляр: так його роздуми видно в метриках окремо від роботи виконавців.
        manager_llm=new_llm(),
        verbose=False,
    )
    result = crew.kickoff()

    print("\n\n\n----- Результат відділу -----")
    print(result.raw)

    usage = crew.usage_metrics
    m = Metrics(
        framework="CrewAI",
        step="Крок 3 — ієрархія",
        calls=usage.successful_requests,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        notes=[
            "порівняйте з кроком 2: зайві виклики — це роздуми менеджера, а не робота",
            "маршрут недетермінований: наступний прогін може залучити інших виконавців",
        ],
    )
    m.report()
