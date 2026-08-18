"""КРОК 3b (CrewAI). Умовний перехід БЕЗ менеджера: розгалуження за ціною `if`.

На кроці 3 маршрут обирав менеджер — і кожен його вибір коштував виклику LLM.
Але більшість «динаміки» у реальних пайплайнах — це не вибір виконавця, а одне
питання «чи взагалі потрібен цей крок». На нього відповідає звичайна Python-
функція, і жодного агента для цього не треба.

`ConditionalTask` — це `Task` з полем `condition`: функція, яка бере результат
ПОПЕРЕДНЬОЇ задачі і повертає True/False. False — задача не виконується взагалі,
у виводах на її місці лишається порожній `TaskOutput`.

Що показуємо: процес лишається `Process.sequential`, `manager_llm` немає,
а маршрут усе одно розгалужується. Порівняйте `викликів LLM` з кроком 3.

Запуск:  .venv/bin/python 01_crewai/c3b_conditional.py
         .venv/bin/python 01_crewai/c3b_conditional.py --skip   # гілка «повернення не треба»

Обмеження, які варто назвати вголос (перевірено по crewai 1.15.16):
* умовна задача не може бути першою — їй потрібен попередній вивід;
* `condition` бачить лише ОСТАННІЙ вивід (`task_outputs[-1]`), а не весь прогін;
* це пропуск кроку, а не стрибок: назад, вперед через два або в цикл — тільки Flow.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c1_agent import investigate, support_agent
from c2_pipeline import refund_agent
from c3_hierarchical import writer_agent
from crewai import Crew, Process, Task
from crewai.tasks.conditional_task import ConditionalTask

import trace_llm
from common import Metrics, banner

# Прапорець для лекції: примусово заганяє прогін у гілку «повернення не потрібне»,
# щоб на екрані було видно сам пропуск, а не лише щасливий шлях.
FORCE_SKIP = "--skip" in sys.argv


# ── Умова: звичайна Python-функція, а не агент ──────────────────────────────
# Аргумент — TaskOutput попередньої задачі. Ніякого виклику LLM тут немає:
# це той самий `if`, який ви написали б у будь-якому сервісі.
#
# Слабке місце видно неозброєним оком: ми парсимо вільний текст, який згенерувала
# модель. Саме тому в проді на такий стик ставлять structured output, а не `in`.
def refund_needed(output) -> bool:
    if FORCE_SKIP:
        print("\n[умова] --skip: рахуємо, що дубль НЕ підтверджено")
        return False
    text = (output.raw or "").lower()
    decision = "дубл" in text or "pay-3002" in text
    print(f"\n[умова] дубль підтверджено? -> {decision} (жодного виклику LLM)")
    return decision


# ── Умовна задача: та сама робота, що на кроці 2, але з вимикачем ───────────
do_refund = ConditionalTask(
    condition=refund_needed,
    description=(
        "За висновком колеги оформи повернення коштів рівно за один платіж — "
        "той, що визнаний дублем."
    ),
    expected_output="Один рядок українською: за яким платежем оформлено повернення.",
    agent=refund_agent,
    context=[investigate],
)

# ── Фінальний крок виконується завжди ───────────────────────────────────────
# Якщо повернення пропущено, у context приїде порожній рядок — і лист клієнту
# треба вміти написати й у такому випадку. Це не деталь реалізації, а вимога
# до промпту: пропущений крок мовчить, а не сигналить про себе.
reply = Task(
    description=(
        "Напиши клієнту коротку відповідь. Про повернення суди ВИКЛЮЧНО за "
        "останнім блоком контексту — тим, де мав бути результат оператора "
        "повернень. Є в ньому ID платежу — пиши, що кошти повертаємо. Порожній "
        "блок — пиши, що повернення поки не оформлене і заявку передано на "
        "додаткову перевірку. Висновок першого агента на це рішення не впливає."
    ),
    expected_output="Лист клієнту українською, максимум 5 рядків.",
    agent=writer_agent,
    context=[investigate, do_refund],
)


if __name__ == "__main__":
    banner(
        "CrewAI",
        "Крок 3b — умовний перехід без менеджера",
        "розгалуження робить Python-функція, а не ще один агент",
    )

    # Трейс вимикається одним рядком: закоментуйте його — і вивід стане звичайним.
    # trace_llm.on()

    crew = Crew(
        agents=[support_agent, refund_agent, writer_agent],
        tasks=[investigate, do_refund, reply],
        process=Process.sequential,  # менеджера немає: manager_llm не заданий
        verbose=False,
    )
    result = crew.kickoff()

    skipped = not (do_refund.output and do_refund.output.raw)
    print("\n\n--- Крок «повернення» ---")
    print("ПРОПУЩЕНО (порожній TaskOutput)" if skipped else do_refund.output.raw)

    print("\n--- Лист клієнту ---")
    print(result.raw)

    usage = crew.usage_metrics
    m = Metrics(
        framework="CrewAI",
        step="Крок 3b — ConditionalTask",
        calls=usage.successful_requests,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        notes=[
            "розгалуження безкоштовне: умова — Python-функція, а не виклик LLM",
            "порівняйте з кроком 3: там ту саму динаміку оплачували роздумами менеджера",
            "запустіть з --skip: у пропущеної гілки виклики LLM просто зникають",
        ],
    )
    m.report()
