"""КРОК 3 (Microsoft Agent Framework). Груповий чат: маршрут обирає оркестратор.

На кроці 2 черговість учасників задали ми. Тут її не задає ніхто з людей:
є троє агентів і оркестратор — окремий агент, який перед кожним ходом дивиться
на розмову й вирішує, кому говорити далі.

Це та сама ідея, що й ієрархія в CrewAI, але механізм видно чіткіше: кожен
раунд починається зі зайвого виклику LLM «а хто наступний?». Порівняйте
`викликів LLM` тут і на кроці 2 — це і є ціна динамічної координації.

Детермінована альтернатива коштує один рядок: замість `orchestrator_agent=`
передати `selection_func=` — звичайну Python-функцію вибору наступного.
Тоді координація безкоштовна, але й гнучкості нуль.

Запуск:  .venv/bin/python 02_msagent/m3_groupchat.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_framework.orchestrations import GroupChatBuilder
from m1_agent import client, metrics, support_agent
from m2_pipeline import refund_agent

from common import TICKET, banner

import trace_llm

# ── Третій учасник: без інструментів, тільки текст для клієнта ──────────────
writer_agent = client.as_agent(
    name="writer",
    middleware=[trace_llm.whoami],
    instructions=(
        "Ти пишеш клієнту фінальну відповідь: коротко, ввічливо, українською, "
        "без ID транзакцій і жаргону, з чітким «що буде далі». Максимум 4 рядки."
    ),
)

# ── Груповий чат ────────────────────────────────────────────────────────────
# orchestrator_agent — це агент-диспетчер. Ми не описуємо йому маршрут,
# він виводить його з розмови сам. max_rounds — запобіжник: без нього
# недетермінований чат може крутитися довше, ніж ми готові платити.
group_chat = (
    GroupChatBuilder(
        participants=[support_agent, refund_agent, writer_agent],
        orchestrator_agent=client.as_agent(
            name="orchestrator",
            middleware=[trace_llm.whoami],
            instructions=(
                "Ти координуєш роботу над тікетом підтримки. Порядок такий: "
                "спочатку support встановлює факти, потім refund_operator "
                "оформлює повернення, потім writer пише відповідь клієнту. "
                "Коли відповідь клієнту готова — завершуй."
            ),
        ),
        output_from="all",  # хочемо бачити репліки всіх учасників, а не лише останнього
    )
    .with_max_rounds(5)
    .build()
)


async def main() -> None:
    # Щоб побачити кожен запит до моделі цілком:
    # trace_llm.on()
    
    banner(
        "Microsoft Agent Framework",
        "Крок 3 — груповий чат",
        "оркестратор обирає, кому говорити, і кожен вибір — виклик LLM",
    )

    metrics.step = "Крок 3 — груповий чат"
    result = await group_chat.run(TICKET)

    print("\n\n\n-------- Хто говорив і що сказав ---")
    for response in result.get_outputs():
        author = response.messages[-1].author_name or "?"
        print(f"[{author}] {response.text}")

    metrics.notes = [
        "порівняйте з кроком 2: різниця у викликах — це робота оркестратора, а не робота над тікетом",
        "маршрут недетермінований: наступний прогін може дати інший порядок",
    ]
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())
