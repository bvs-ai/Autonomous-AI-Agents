"""ReAct «з нуля» на StateGraph: той самий граф, що ми розглядали в 016, але
зібраний руками -- заради двох речей, яких у готовому агенті немає.

Тут закривається питання, яке лишилось відкритим у лекції 1. Там демо 016
показало: «фреймворк дає цикл, а не надійність -- запобіжники з 011 усе одно
писати самому». Але в 011 вони жили у власному while, а тут цикл чужий.
Відповідь: у графі є куди їх вставити -- умовне ребро і вузол інструментів.

  1. StopController (017) у ролі умовного ребра. У готовому агенті ліміт один --
     recursion_limit, і він падає винятком; тут на кожній ітерації перевіряються
     всі критерії одразу, а користувач отримує ПРИЧИНУ зупинки.
  2. safe_tool_node замість стандартного ToolNode -- це той самий блок захисту,
     що в 011 лекції 1 стояв усередині циклу, тільки тепер він вузол графа.
     Стандартний ToolNode на виняток усередині інструмента валить увесь граф;
     наш ловить його і повертає ToolMessage з описом збою -- модель отримує
     Observation і може виправитись. Там же allowlist: виклик неіснуючого
     інструмента не KeyError, а відповідь зі списком доступних.

AgentState -- TypedDict; messages має reducer add_messages (нові повідомлення
дописуються, а не затирають список), step_count і total_tokens -- звичайні поля.

Потребує заповненого .env і requirements_langgraph.txt.
"""

import os
from datetime import date, timedelta
from typing import Annotated, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from stop_controller import StopController

load_dotenv()

RETURN_WINDOW_DAYS = 30


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


@tool
def query_orders(status: str) -> list[dict]:
    """Отримати список замовлень із заданим статусом ('повернення' або 'доставлено')."""
    return [o for o in ORDERS if o["status"] == status]


@tool
def check_return_policy(order_id: str) -> dict:
    """Перевірити, чи можна ще повернути замовлення за його ідентифікатором (напр. 'A-1001')."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        raise KeyError(f"замовлення {order_id} немає в базі")  # навмисно виняток, а не dict
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= RETURN_WINDOW_DAYS}


TOOLS = [query_orders, check_return_policy]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    step_count: int
    total_tokens: int


stop_controller = StopController(max_steps=8, max_tokens=50_000, timeout=60.0, max_repeats=3)

model = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["OPENAI_BASE_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
    temperature=0,
).bind_tools(TOOLS)


def call_model(state: AgentState) -> dict:
    """Вузол LLM: Thought (неявний) + Action (tool_calls) за поточним контекстом."""
    response = model.invoke(state["messages"])
    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "messages": [response],
        "step_count": state.get("step_count", 0) + 1,
        "total_tokens": state.get("total_tokens", 0) + usage.get("total_tokens", 0),
    }


def should_continue(state: AgentState) -> str:
    """Умовне ребро -- тут живуть стоп-критерії."""
    last_message = state["messages"][-1]

    tool_calls = []
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        tool_calls = [f"{c['name']}:{c['args']}" for c in last_message.tool_calls]

    stop, reason = stop_controller.should_stop(
        step=state.get("step_count", 0), tokens=state.get("total_tokens", 0), tool_calls=tool_calls
    )
    if stop:
        print(f"[STOPPED_BY_CONTROLLER] {reason}")
        return "end"

    return "tools" if tool_calls else "end"


def safe_tool_node(state: AgentState) -> dict:
    """Виконання інструментів так, щоб граф не падав НІКОЛИ:
    Observation повертається і на невідомий інструмент, і на виняток усередині."""
    results = []

    for call in state["messages"][-1].tool_calls:
        name = call["name"]

        if name not in TOOLS_BY_NAME:
            content = f"Помилка: інструмент '{name}' не існує. Доступні: {list(TOOLS_BY_NAME)}"
        else:
            try:
                content = str(TOOLS_BY_NAME[name].invoke(call["args"]))
            except Exception as error:  # noqa: BLE001 -- захисний вузол навмисно ловить усе
                content = f"Помилка виконання {name}: {type(error).__name__}: {error}"

        print(f"[TOOL_CALL_RESULT] {content[:110]}")
        results.append(ToolMessage(content=content, tool_call_id=call["id"]))

    return {"messages": results}


workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", safe_tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
workflow.add_edge("tools", "agent")

graph = workflow.compile()


def run(question: str) -> None:
    stop_controller.reset()  # контролер зберігає стан прогону -- скидаємо перед новим
    print(f"[USER] {question}")
    result = graph.invoke({"messages": [("user", question)], "step_count": 0, "total_tokens": 0})
    print(f"[FINAL_ANSWER] {result['messages'][-1].content[:300]}")
    print(f"[BUDGET] кроків: {result['step_count']}, токенів: {result['total_tokens']}\n")


if __name__ == "__main__":
    run("Які замовлення на поверненні ще можна повернути?")

    # Замовлення A-9999 не існує -- інструмент кине KeyError. Зі стандартним
    # ToolNode тут би впав увесь граф; safe_tool_node перетворює виняток на
    # Observation, і модель сама пояснює користувачу, що замовлення не знайдено.
    run("Чи можна повернути замовлення A-9999?")
