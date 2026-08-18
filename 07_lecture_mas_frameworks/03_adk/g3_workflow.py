"""КРОК 3 (Google ADK). Граф: маршрут вирішує код, а не модель.

CrewAI на кроці 3 віддав маршрут менеджеру-LLM, MAF — оркестратору-LLM.
ADK 2.x пропонує протилежне: новий `Workflow` — це явний граф вузлів і ребер,
де розгалуження робить звичайна Python-функція.

Тут це видно буквально: вузол `check_policy` не звертається до моделі взагалі.
Він читає суму й ліміт і виставляє `ctx.route` — «повертаємо самі» або
«ескалюємо людині». Порівняйте `викликів LLM` із кроком 3 у CrewAI: на
координацію тут витрачено рівно нуль.

Правило регламенту (ліміт повернення) — саме той випадок, коли віддавати
рішення моделі не треба: воно записане в документі, воно перевіряється, і за
нього відповідає компанія, а не ймовірності.

Спробуйте на лекції: зменште REFUND_LIMIT_USD у common.py до 10 — граф піде
іншою гілкою, і жоден виклик LLM на це не витратиться.

Запуск:  .venv/bin/python 03_adk/g3_workflow.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trace_llm
from g1_agent import run, support_agent
from g2_pipeline import refund_agent
from google.adk.agents.context import Context
from google.adk.workflow import START, Workflow, node

from common import REFUND_LIMIT_USD, TICKET, Metrics, banner

# Сума спірного списання. У житті її дістали б із виписки; для демо тримаємо
# поруч, щоб на лекції було видно, з чим саме порівнюється ліміт.
DISPUTED_AMOUNT_USD = 49.99


# ── Розгалуження без моделі ─────────────────────────────────────────────────
# Вузол графа — звичайна async-функція. Вона виставляє ctx.route, і ADK за
# цим значенням обирає наступний вузол. Нуль викликів LLM, повна повторюваність.
@node(name="check_policy")
async def check_policy(ctx: Context) -> None:
    """Регламент: до ліміту повертаємо самі, вище — віддаємо людині."""
    if DISPUTED_AMOUNT_USD <= REFUND_LIMIT_USD:
        print(f"[check_policy] {DISPUTED_AMOUNT_USD} <= {REFUND_LIMIT_USD} → повертаємо самі")
        ctx.route = "auto"
    else:
        print(f"[check_policy] {DISPUTED_AMOUNT_USD} > {REFUND_LIMIT_USD} → до людини")
        ctx.route = "human"


@node(name="escalate")
async def escalate(ctx: Context) -> None:
    """Гілка для людини: тікет у чергу, автоматичного повернення немає."""
    print("[escalate] Тікет поставлено в чергу на ручний розгляд.")


# Вузол-агент, що приймає вхід від попереднього вузла, має бути single_turn:
# режим chat (типовий для агента) живе історією розмови й не вміє читати вхід
# вузла — Workflow таке відхиляє ще на валідації.
refund_agent.mode = "single_turn"

# ── Граф ────────────────────────────────────────────────────────────────────
# Ребра описуються ланцюжком, а розгалуження — звичайним словником
# «значення route → вузол». Це весь опис маршруту; більше його ніде немає.
billing_graph = Workflow(
    name="billing_workflow",
    edges=[
        (START, support_agent, check_policy, {"auto": refund_agent, "human": escalate}),
    ],
)


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()

    banner(
        "Google ADK",
        "Крок 3 — граф Workflow",
        "розгалуження робить код: нуль викликів LLM на координацію",
    )

    metrics = Metrics(framework="ADK", step="Крок 3 — граф")
    await run(billing_graph, TICKET, metrics, session_id="g3")

    metrics.notes = [
        "маршрут обрала функція check_policy — виклики LLM пішли тільки на роботу",
        "результат повторюваний: той самий вхід дає той самий маршрут",
        "Workflow — заміна застарілим SequentialAgent/ParallelAgent з 1.x",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
