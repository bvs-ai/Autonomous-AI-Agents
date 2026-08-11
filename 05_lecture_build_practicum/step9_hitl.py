"""КРОК 9. Human-in-the-Loop: interrupt/approval для ризикового інструмента.

Інструменти розділено на два вузли графа: safe_tools і risky_tools (file_write).
Граф компілюється з interrupt_before=["risky_tools"] — виконання зупиняється
ПЕРЕД ризиковим викликом, стан лежить у checkpointer і чекає рішення оператора.

Запуск:  .venv/bin/python step9_hitl.py            # обидва сценарії автоматично
         .venv/bin/python step9_hitl.py --ask      # питає підтвердження в консолі
"""
import json
import os
import sys
import uuid

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from step1_setup import get_text, llm
from step2_tools import file_write, safe_tools
from step3_react import SYSTEM_PROMPT

# Усі інструменти, включаючи ризиковий file_write
hitl_tools = safe_tools + [file_write]
llm_with_hitl_tools = llm.bind_tools(hitl_tools)

HITL_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    "\nТакож ти маєш інструмент file_write для запису у файл. "
    "Це ризикова операція — система запитає підтвердження оператора."
)


def hitl_agent_node(state: MessagesState) -> dict:
    """Вузол агента з HITL-інструментами."""
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=HITL_SYSTEM_PROMPT)] + messages
    response = llm_with_hitl_tools.invoke(messages)
    return {"messages": [response]}


def is_risky_tool(state: MessagesState) -> str:
    """Маршрутизація: ризиковий виклик → risky_tools, звичайний → safe_tools, інакше END."""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            if tc["name"] == "file_write":
                return "risky"
        return "safe_tools"
    return END


# Побудова HITL-графа
hitl_graph = StateGraph(MessagesState)
hitl_graph.add_node("agent", hitl_agent_node)
hitl_graph.add_node("safe_tools", ToolNode(safe_tools))
hitl_graph.add_node("risky_tools", ToolNode([file_write]))
hitl_graph.add_edge(START, "agent")
hitl_graph.add_conditional_edges(
    "agent", is_risky_tool,
    {"safe_tools": "safe_tools", "risky": "risky_tools", END: END}
)
hitl_graph.add_edge("safe_tools", "agent")
hitl_graph.add_edge("risky_tools", "agent")


def demo_hitl(approval: bool, ask_operator: bool = False):
    """Демонстрація Human-in-the-Loop: approve або reject."""
    with SqliteSaver.from_conn_string("hitl_checkpoints.db") as checkpointer:
        # Компілюємо з interrupt_before на ризиковому вузлі
        hitl_agent = hitl_graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["risky_tools"]
        )

        # Свіжий thread_id на кожен прогін, щоб сценарії не змішувались
        thread_id = f"hitl-demo-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # 1) Запит, що потребує запису у файл
        print("=" * 60)
        print(f"📌 Запит: записати дані у файл  (thread={thread_id})")
        hitl_agent.invoke(
            {"messages": [HumanMessage(
                content="Запиши у файл report.txt текст: 'Звіт від агента: усі системи працюють.'"
            )]},
            config=config
        )

        # 2) Перевіряємо стан — має бути interrupt перед risky_tools
        snapshot = hitl_agent.get_state(config)
        print("\n⏸️  Виконання призупинено (interrupt_before='risky_tools')")
        print(f"   Наступний вузол: {snapshot.next}")

        # Показуємо, що саме агент хоче зробити
        pending = snapshot.values["messages"][-1]
        if getattr(pending, "tool_calls", None):
            for tc in pending.tool_calls:
                print(f"   🔧 Інструмент: {tc['name']}")
                print(f"   📝 Аргументи: {json.dumps(tc['args'], ensure_ascii=False)}")

        # 3) Рішення оператора
        if ask_operator:
            answer = input("\n❓ Дозволити запис у файл? [y/N]: ").strip().lower()
            approval = answer in ("y", "yes", "т", "так")
        print(f"\n{'✅ Оператор затвердив' if approval else '❌ Оператор відхилив'} операцію.")

        if approval:
            # Продовжуємо виконання (None = без нових повідомлень,
            # граф просто йде далі з місця зупинки)
            result = hitl_agent.invoke(None, config=config)
            print(f"\n🤖 {get_text(result['messages'][-1].content)}")
            print(f"   Файл на диску: {'є' if os.path.exists('report.txt') else 'немає'}")
        else:
            # Відхилення: підставляємо результат ЗАМІСТЬ виконання вузла.
            # as_node="risky_tools" каже графу: «вважай, що цей вузол відпрацював
            # і повернув ось це». file_write при цьому не викликається.
            hitl_agent.update_state(
                config,
                {"messages": [ToolMessage(
                    content="Операцію відхилено оператором.",
                    tool_call_id=pending.tool_calls[0]["id"]
                )]},
                as_node="risky_tools"
            )
            after_update = hitl_agent.get_state(config)
            print(f"   Після update_state наступний вузол: {after_update.next}"
                  f"  (було: {snapshot.next})")

            # Далі — таке саме продовження, як і при затвердженні
            result = hitl_agent.invoke(None, config=config)
            print(f"\n🤖 {get_text(result['messages'][-1].content)}")

        final = hitl_agent.get_state(config)
        print(f"   Стан після рішення — наступний вузол: {final.next or '(граф завершено)'}")

        # Історія чекпоінтів: видно, ЯК саме було ухвалено рішення.
        # source="update" — підміна результату вузла; source="input" — новий вхід.
        print("   Історія чекпоінтів (step / source / next):")
        for st in list(hitl_agent.get_state_history(config))[::-1]:
            print(f"      {st.metadata.get('step'):>3}  "
                  f"{str(st.metadata.get('source')):<7} {st.next}")


if __name__ == "__main__":
    if "--ask" in sys.argv:
        demo_hitl(approval=False, ask_operator=True)
    else:
        # Сценарій 1: відхилення (файл не з'являється)
        if os.path.exists("report.txt"):
            os.remove("report.txt")
        print("\n🔴 СЦЕНАРІЙ 1: ВІДХИЛЕННЯ")
        demo_hitl(approval=False)
        print(f"\n   report.txt на диску: {'є' if os.path.exists('report.txt') else 'немає'} "
              f"— ризиковий інструмент не виконувався")

        # Сценарій 2: затвердження (файл записується)
        print("\n\n🟢 СЦЕНАРІЙ 2: ЗАТВЕРДЖЕННЯ")
        demo_hitl(approval=True)

    print("\n✅ Демонстрація HITL завершена.")
