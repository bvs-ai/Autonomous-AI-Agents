"""КРОК 1 (Google ADK). Агент, Runner, Session — і потік подій замість відповіді.

Третій фреймворк, та сама задача. Опис агента тут найкоротший із трьох:
`LlmAgent(name, model, instruction, tools)` — і все, ніяких ролей та клієнтів.

Головна ж відмінність ADK не в описі агента, а в запуску. CrewAI повертає
результат, MAF повертає результат — ADK повертає **потік подій**: окремо текст,
окремо виклик інструмента, окремо його відповідь. Через цей самий потік
працюють Dev UI, трасування й оцінка, тому вчитися читати його варто одразу.

Ще один обов'язковий у ADK об'єкт — Session: пам'ять однієї розмови. Її
створюють явно, і саме через неї на кроці 2 агенти передаватимуть дані.

Запуск:  .venv/bin/python 03_adk/g1_agent.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trace_llm
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from common import MODEL, TICKET, Metrics, banner, get_payments

APP_NAME = "mas_demo"
USER_ID = "student"

# ── Агент ───────────────────────────────────────────────────────────────────
# Інструмент — знову звичайна функція з common.py, без обгортки: ADK, як і MAF,
# збирає опис для моделі з сигнатури й docstring.
support_agent = LlmAgent(
    name="support",
    model=MODEL,
    description="Спеціаліст підтримки з білінгу",  # опис для ІНШИХ агентів, не для моделі
    instruction=(
        "Ти спеціаліст підтримки платіжного сервісу. "
        "Спочатку подивись виписку по платежах інструментом get_payments, "
        "і лише потім роби висновок. Відповідай українською, максимум 5 рядків."
    ),
    tools=[get_payments],
)


async def run(agent: LlmAgent, message: str, metrics: Metrics, session_id: str) -> str:
    """Один прогін агента: розбирає потік подій і рахує метрики.

    Ця функція — спільна для всіх трьох кроків ADK. Тут видно, що саме
    приходить із потоку: хто автор події, текст це чи виклик інструмента,
    і скільки токенів коштував кожен крок.
    """
    # Плагін реєструється на застосунок, а не на агента: у кроках 2 і 3
    # він так само побачить усіх учасників без жодної правки.
    app = App(name=APP_NAME, root_agent=agent, plugins=[trace_llm.plugin])
    runner = InMemoryRunner(app=app)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    content = types.Content(role="user", parts=[types.Part(text=message)])

    answer = ""
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        if event.usage_metadata:  # подія прийшла від моделі — це виклик LLM
            metrics.calls += 1
            metrics.prompt_tokens += event.usage_metadata.prompt_token_count or 0
            metrics.completion_tokens += event.usage_metadata.candidates_token_count or 0
        for part in (event.content.parts if event.content else []) or []:
            if part.function_call:
                print(f"[{event.author}] викликає {part.function_call.name}")
            elif part.text and part.text.strip():
                answer = part.text.strip()
                print(f"[{event.author}] {answer}")
    return answer


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()

    banner(
        "Google ADK",
        "Крок 1 — агент і Runner",
        "запуск повертає не рядок, а потік подій",
    )

    metrics = Metrics(framework="ADK", step="Крок 1 — один агент")
    await run(support_agent, TICKET, metrics, session_id="g1")

    metrics.notes = [
        "Runner + Session обов'язкові навіть для одного агента — це рантайм ADK",
        "події видно всі: і текст, і виклик інструмента; на них тримається Dev UI",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
