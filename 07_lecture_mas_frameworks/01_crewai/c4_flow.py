"""ОПЦІЙНО (CrewAI). Той самий сценарій, але маршрут описано як Flow.

Крок 2 (`c2_pipeline.py`) — це Crew: список задач, які фреймворк виконує
підряд. Крок 3 — ієрархія: маршрут обирає менеджер-LLM. Flow — третій спосіб,
між ними: **маршрут пишемо ми звичайним Python-кодом**, а кожен вузол за
потреби запускає власний маленький Crew.

Що тут видно за дві хвилини:

* `@start` / `@listen` / `@router` — граф із методів класу, як у LangGraph;
* `self.state` — спільний стан між вузлами (тут — pydantic-модель);
* `@router` вирішує розгалуження **без виклику LLM**: це звичайний `if`.
  Порівняйте з кроком 3, де за кожне рішення платимо викликом моделі.

Як задаються переходи (усе — в декораторах, окремого опису графа немає):

    @start()              вхідна точка: з цього методу починається kickoff()
    @router(investigate)  спрацьовує ПІСЛЯ вказаного методу; рядок, який він
                          повернув, — це ім'я події
    @listen("refund")     підписка на подію з таким іменем

Тобто ребро графа — це не «виклич наступний метод», а «оголоси подію, і
відпрацює той, хто на неї підписаний». Підписників може бути кілька, а вузол
не знає, хто піде за ним. У @router і @listen приймається і посилання на
метод (@router(investigate)), і рядок з його іменем — посилання надійніше:
за друкарську помилку в ньому впаде імпорт, а не тихо обірветься граф.

Агентів не переписуємо — беремо готових із кроків 1 і 2.

Запуск:  .venv/bin/python 01_crewai/c4_flow.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from c1_agent import support_agent
from c2_pipeline import refund_agent
from crewai import Crew, Task
from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel

import trace_llm
from common import TICKET, Metrics, banner

# Сюди складаємо usage кожного міні-Crew, щоб наприкінці підбити спільні метрики.
_USAGE = []


def run_crew(agent, description: str, expected_output: str) -> str:
    """Один вузол Flow = один маленький Crew з однієї задачі."""
    crew = Crew(agents=[agent], tasks=[Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
    )], verbose=False)
    result = crew.kickoff()
    _USAGE.append(crew.usage_metrics)
    return result.raw


# ── Стан потоку ─────────────────────────────────────────────────────────────
# У Crew дані між задачами передаються текстом через Task.context. У Flow є
# явний об'єкт стану: будь-який вузол читає й пише його поля.
class TicketState(BaseModel):
    ticket: str = TICKET
    report: str = ""      # висновок першого агента
    answer: str = ""      # фінальна відповідь
    payments: list[str] = []  # ID платежів, які згадав перший агент


class SupportFlow(Flow[TicketState]):
    """Граф із трьох вузлів: розслідувати → розгалуження → повернути / закрити."""

    @start()
    def investigate(self) -> None:
        self.state.report = run_crew(
            support_agent,
            f"Розберися зі скаргою клієнта.\n\nТікет:\n{self.state.ticket}",
            "Стислий висновок українською: чи підтверджується подвійне списання, "
            "які саме платежі це показують. Максимум 5 рядків.",
        )
        # Парсимо ID платежів звичайним regex — це теж «код, а не модель».
        self.state.payments = re.findall(r"PAY-\d+", self.state.report)

    # ── Розгалуження ────────────────────────────────────────────────────────
    # Повернений рядок — це ім'я події, на яку підписані вузли нижче.
    # Жодного виклику LLM тут немає: рішення ухвалює правило, яке видно очима.
    @router(investigate)
    def decide(self) -> str:
        return "refund" if len(self.state.payments) >= 2 else "no_refund"

    @listen("refund")
    def make_refund(self) -> None:
        self.state.answer = run_crew(
            refund_agent,
            "За висновком колеги оформи повернення коштів.\n\n"
            f"Висновок:\n{self.state.report}",
            "Один рядок українською: за яким платежем оформлено повернення.",
        )

    @listen("no_refund")
    def close_ticket(self) -> None:
        # Гілка без LLM узагалі: дешева відповідь там, де модель не потрібна.
        self.state.answer = "Дубль не підтверджено — повернення не оформлюємо."


if __name__ == "__main__":
    banner(
        "CrewAI",
        "Опційно — Flow",
        "маршрут описано кодом (@start/@listen/@router), стан живе в self.state",
    )

    # Трейс вимикається одним рядком: закоментуйте його — і вивід стане звичайним.
    # trace_llm.on()

    # Панелі «Flow Method Running» друкує вбудований слухач подій CrewAI
    # Штатний спосіб прибрати їх — режим TUI:
    # from crewai.events.listeners.tracing.utils import set_tui_mode
    # set_tui_mode(True)
    
    flow = SupportFlow()
    flow.kickoff()

    print("\n\n--- Стан після прогону ---")
    print("payments:", flow.state.payments)
    print("гілка   :", "refund" if len(flow.state.payments) >= 2 else "no_refund")

    print("\n--- Висновок першого вузла ---")
    print(flow.state.report)

    print("\n--- Результат гілки ---")
    print(flow.state.answer)

    m = Metrics(
        framework="CrewAI",
        step="Опційно — Flow",
        calls=sum(u.successful_requests for u in _USAGE),
        prompt_tokens=sum(u.prompt_tokens for u in _USAGE),
        completion_tokens=sum(u.completion_tokens for u in _USAGE),
        notes=[
            "розгалуження безкоштовне: @router — це if, а не ще один агент",
            "гілка no_refund не викликає LLM жодного разу",
        ],
    )
    m.report()
