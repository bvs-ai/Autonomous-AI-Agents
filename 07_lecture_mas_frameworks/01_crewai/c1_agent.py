"""КРОК 1 (CrewAI). Агент з роллю та інструментом.

CrewAI описує агента не системним промптом, а трьома полями: role, goal,
backstory. Виглядає як метафора «команди», але фізично це шаблон, з якого
фреймворк складає звичайний системний промпт.

Демо друкує цей згенерований промпт. Це головне, що варто побачити на кроці 1:
жодної магії ролей немає, є генератор тексту — і тепер зрозуміло, чому від
формулювання backstory реально залежить поведінка.

Запуск:  .venv/bin/python 01_crewai/c1_agent.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crewai import LLM, Agent, Crew, Task
from crewai.tools import tool

import trace_llm
from common import MODEL, TICKET, Metrics, banner
from common import get_payments as _get_payments

# ── Обгортка інструмента ────────────────────────────────────────────────────
# Функція вже написана у common.py. CrewAI треба лише накинути декоратор:
# ім'я інструмента береться з аргументу, опис — з docstring.
# Порівняйте з 02_msagent/ і 03_adk/ — там ця сама функція йде взагалі без обгортки.


@tool("Get Payments")
def get_payments(customer_id: str) -> str:
    """Повертає список платежів клієнта за останні місяці."""
    return _get_payments(customer_id)


# ── Модель ──────────────────────────────────────────────────────────────────
# Префікс провайдера обов'язковий: за рядком 'gemini/<модель>' CrewAI обирає
# потрібного клієнта. Без префікса він мовчки візьме OpenAI-клієнт.
# У 02_msagent/ і 03_adk/ провайдер заданий самим класом клієнта, тому там
# та сама MODEL йде без префікса.
def new_llm() -> LLM:
    """Окремий екземпляр LLM для кожного агента.

    Лічильники токенів у CrewAI живуть усередині об'єкта LLM і накопичуються
    за весь його час життя, а Crew.calculate_usage_metrics() збирає їх циклом
    по агентах. Якщо роздати одну модель двом агентам, той самий лічильник
    додасться двічі: 4 реальні виклики покажуться як 8. Тому — по екземпляру
    на агента (і окремий для менеджера на кроці 3).
    """
    return LLM(model=f"gemini/{MODEL}")


llm = new_llm()

# ── Агент: три поля замість системного промпту ──────────────────────────────
support_agent = Agent(
    role="Спеціаліст підтримки з білінгу",
    goal="Розібратися у скарзі клієнта на списання та встановити факти",
    backstory=(
        "Ти працюєш у підтримці платіжного сервісу третій рік. "
        "Ти ніколи не робиш висновків без даних: спочатку дивишся виписку "
        "по платежах, і лише потім формулюєш відповідь."
    ),
    tools=[get_payments],
    llm=llm,
    verbose=False,
    allow_delegation=False,  # least privilege: делегування вимкнене за замовчуванням
    max_iter=5,  # аварійний ліміт кроків — щоб агент не крутився вічно
)

# ── Задача ──────────────────────────────────────────────────────────────────
# Два обов'язкових поля: що робити (description) і як має виглядати
# результат (expected_output). Друге — не косметика: саме воно тримає формат.
investigate = Task(
    description=f"Розберися зі скаргою клієнта.\n\nТікет:\n{TICKET}",
    expected_output=(
        "Стислий висновок українською: чи підтверджується подвійне списання, "
        "які саме платежі це показують, що робити далі. Максимум 5 рядків."
    ),
    agent=support_agent,
)


# Метод не належить до основної функціональності, можна пропустити.
def show_generated_prompt() -> None:
    """Друкує обидва повідомлення, які CrewAI відправить у модель.

    Те саме, що фреймворк робить на запуску, тільки вручну: system збирається
    з role/goal/backstory, user — із шаблону, куди підставляється текст задачі.
    """
    from crewai.utilities.agent_utils import (
        get_tool_names,
        render_text_description_and_args,
    )
    from crewai.utilities.prompts import Prompts

    # Перемкніть на False, щоб побачити другий режим: замість окремого поля запиту
    # CrewAI вкладе опис інструментів у текст промпту разом із ReAct-форматом
    # (Thought / Action / Action Input), а відповідь моделі доведеться парсити.
    NATIVE_TOOL_CALLING = True

    built = Prompts(
        agent=support_agent,
        has_tools=True,
        use_system_prompt=True,
        use_native_tool_calling=NATIVE_TOOL_CALLING,
    ).task_execution()

    # Шаблони приходять із плейсхолдерами; на запуску їх заповнює виконавець
    # (crew_agent_executor._format_prompt). Робимо те саме руками:
    #   {input}      → task.prompt(): description + expected_output;
    #   {tools}      → опис інструментів для ReAct-режиму;
    #   {tool_names} → їхні імена, з яких моделі дозволено вибирати.
    def fill(template: str) -> str:
        return (
            template.replace("{input}", investigate.prompt())
            .replace("{tools}", render_text_description_and_args(support_agent.tools))
            .replace("{tool_names}", get_tool_names(support_agent.tools))
        )

    print("\n--- system: зібраний із role/goal/backstory ---")
    print(fill(built["system"]))
    print("\n--- user: зібраний із description + expected_output ---")
    print(fill(built["user"]))
    print("--- кінець промпту ---")


if __name__ == "__main__":
    banner("CrewAI", "Крок 1 — агент і роль", "role/goal/backstory — це шаблон промпту")

    # Трейс вимикається одним рядком: закоментуйте його — і вивід стане звичайним.
    # trace_llm.on()

    show_generated_prompt()

    crew = Crew(agents=[support_agent], tasks=[investigate], verbose=False)
    result = crew.kickoff()

    print("\n--- Відповідь агента ---")
    print(result.raw)

    usage = crew.usage_metrics
    m = Metrics(
        framework="CrewAI",
        step="Крок 1 — один агент",
        calls=usage.successful_requests,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        notes=["виклики: 1 на роздуми + 1 після інструмента — це базова ціна кроку"],
    )
    m.report()
