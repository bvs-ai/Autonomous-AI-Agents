"""КРОК 3b (Microsoft Agent Framework). Switch-case: маршрут без оркестратора.

На кроці 3 наступного мовця обирав оркестратор — окремий агент, тобто зайвий
виклик LLM перед кожним раундом. Тут маршрут теж динамічний, але обирає його
звичайна Python-функція, і коштує це нуль.

Головна різниця з CrewAI, заради якої цей крок і існує. У CrewAI умовність
всередині `Crew` бінарна: `ConditionalTask` вміє лише виконатись або ні, а справжнє
розгалуження живе в окремому API — `Flow`. У MAF граф — це і є базовий шар:
`WorkflowBuilder.add_switch_case_edge_group()` розводить повідомлення по різних
виконавцях штатно, а `SequentialBuilder` з кроку 2 і `GroupChatBuilder` з кроку 3 —
це надбудови над тим самим графом.

Схема нижче:

    support ──(дубль підтверджено)──> refund_operator ──> writer
            └──────(Default)──────────────────────────────> writer

Запуск:  .venv/bin/python 02_msagent/m3b_switch.py
         .venv/bin/python 02_msagent/m3b_switch.py --skip   # гілка Default
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_framework import AgentExecutorResponse, Case, Default, WorkflowBuilder
from m1_agent import client, metrics, support_agent
from m2_pipeline import refund_agent

from common import TICKET, banner

import trace_llm

# Прапорець для лекції: примусово заганяє прогін у гілку Default.
FORCE_SKIP = "--skip" in sys.argv

# ── Третій учасник ──────────────────────────────────────────────────────────
writer_agent = client.as_agent(
    name="writer",
    middleware=[trace_llm.whoami],
    instructions=(
        "Ти пишеш клієнту фінальну відповідь українською, максимум 4 рядки. "
        "Якщо в розмові є підтвердження оформленого повернення — скажи про це "
        "прямо. Якщо його немає — напиши, що заявку передано на додаткову "
        "перевірку, і повернення поки не оформлене."
    ),
)


# ── Умова на ребрі: звичайна функція, жодного виклику LLM ───────────────────
# Аргумент — те саме повідомлення, яке відправив source. Для агента, загорнутого
# фреймворком, це AgentExecutorResponse: усередині і відповідь агента
# (.agent_response), і вся розмова цілком (.full_conversation).
def refund_needed(response: AgentExecutorResponse) -> bool:
    if FORCE_SKIP:
        print("\n[умова] --skip: рахуємо, що дубль НЕ підтверджено")
        return False
    text = (response.agent_response.text or "").lower()
    decision = "дубл" in text or "pay-3002" in text
    print(f"\n[умова] дубль підтверджено? -> {decision} (жодного виклику LLM)")
    return decision


# ── Граф ────────────────────────────────────────────────────────────────────
# Case перевіряються по порядку, перемагає перший, чия умова дала True;
# Default забирає все, що не підійшло під жодну умову. Ребра приймають самих
# агентів — обгортати їх у власні Executor не потрібно.
workflow = (
    WorkflowBuilder(start_executor=support_agent, output_from=[writer_agent])
    .add_switch_case_edge_group(
        support_agent,
        [
            Case(condition=refund_needed, target=refund_agent),
            Default(target=writer_agent),
        ],
    )
    .add_edge(refund_agent, writer_agent)
    .build()
)


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()

    banner(
        "Microsoft Agent Framework",
        "Крок 3b — switch-case без оркестратора",
        "розгалуження робить умова на ребрі графа, а не ще один агент",
    )

    metrics.step = "Крок 3b — switch-case"
    result = await workflow.run(TICKET)

    print("\n\n\n--- Лист клієнту ---")
    print(result.get_outputs()[-1].text)

    metrics.notes = [
        "маршрут динамічний, але координація безкоштовна: умова — Python-функція",
        "порівняйте з кроком 3: там кожен раунд починався з питання «хто наступний?»",
        "запустіть з --skip: гілка Default веде повз refund_operator, і виклик зникає",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
