"""КРОК 3. ReAct-агент у LangGraph (цикл LLM–tools–LLM).

Граф із двох вузлів: agent (LLM з прив'язаними інструментами) та tools
(виконання інструмента). Умовне ребро tools_condition вирішує, чи є tool_calls
у відповіді LLM: якщо є — йдемо в tools, якщо ні — END. Після tools завжди
повертаємось в agent — це і є цикл.

Запуск:  .venv/bin/python step3_react.py
"""
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from step1_setup import get_text, llm
from step2_tools import safe_tools

# Прив'язуємо інструменти до моделі
llm_with_tools = llm.bind_tools(safe_tools)

# Системний промпт
SYSTEM_PROMPT = """Ти — інтелектуальний асистент-агент. Відповідай українською мовою.
Ти маєш доступ до інструментів: calculator, current_datetime, wikipedia_search, http_get.
Перед відповіддю на фактологічне питання ЗАВЖДИ використовуй відповідний інструмент.
Для обчислень ЗАВЖДИ використовуй calculator, не рахуй самостійно.
Відповідай стисло та по суті. Якщо інструмент повернув помилку, повідом користувача."""


def agent_node(state: MessagesState) -> dict:
    """Вузол агента: викликає LLM із контекстом повідомлень."""
    messages = state["messages"]
    # Додаємо системний промпт, якщо його ще немає
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# Вузол інструментів (prebuilt) 
tool_node = ToolNode(safe_tools)

# Побудова графа
react_graph = StateGraph(MessagesState)
react_graph.add_node("agent", agent_node)
react_graph.add_node("tools", tool_node)
react_graph.add_edge(START, "agent")
react_graph.add_conditional_edges(
    "agent",
    tools_condition,   # перевіряє, чи є tool_calls у відповіді LLM
    {"tools": "tools", END: END}
)
react_graph.add_edge("tools", "agent")  # після tools — назад у agent (цикл)

# Компіляція без checkpointer (буде додано на Кроці 7)
react_agent = react_graph.compile()


if __name__ == "__main__":
    print("✅ ReAct-граф скомпільовано. Вузли:", list(react_graph.nodes))

    test_queries = [
        "Скільки буде 1234 * 5678 + 99?",
        "Яка сьогодні дата?",
        "Хто такий Тарас Шевченко?",
    ]

    for q in test_queries:
        print(f"\n{'='*60}")
        print(f"👤 Запит: {q}")
        result = react_agent.invoke({"messages": [HumanMessage(content=q)]})
        final = result["messages"][-1]
        # get_text — бо Gemini віддає content списком блоків (див. Крок 1)
        print(f"🤖 Відповідь: {get_text(final.content)}")
        # Показуємо траєкторію (які інструменти було використано)
        tool_calls = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        if tool_calls:
            print(f"🔧 Інструменти: {[m.name for m in tool_calls]}")

    print(f"\n{'='*60}")
    print("✅ Тестування ReAct-агента завершено.")

    # Візуалізація графа (бонусна вимога домашнього завдання)
    print("\n📈 Схема графа (Mermaid):")
    print(react_agent.get_graph().draw_mermaid())
