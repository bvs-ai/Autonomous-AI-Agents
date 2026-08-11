"""КРОК 5. Захисні механізми: max_steps, timeout, детекція повторів.

Той самий ReAct-цикл, але стан розширено лічильником кроків, часом старту,
траєкторією та останніми tool_calls. Три рівні захисту:
  1) ліміт кроків MAX_STEPS,
  2) загальний таймаут TIMEOUT_SEC,
  3) детекція повторного виклику того самого інструмента з тими самими аргументами.

Запуск:  .venv/bin/python step5_guards.py
"""
import json
import time
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from step1_setup import get_text, logger
from step2_tools import safe_tools
from step3_react import SYSTEM_PROMPT, llm_with_tools

MAX_STEPS = 10
TIMEOUT_SEC = 120  # загальний таймаут на весь цикл


class GuardedState(TypedDict):
    messages: Annotated[list, add_messages]
    step_count: int
    start_time: float
    trajectory: list       # JSON-траєкторія
    last_tool_calls: list  # для детекції повторів


def guarded_agent_node(state: GuardedState) -> dict:
    """Агент із захистом від зациклення та перевищення часу."""
    step = state.get("step_count", 0) + 1
    start = state.get("start_time") or time.time()
    elapsed = time.time() - start

    # Перевірка ліміту кроків
    if step > MAX_STEPS:
        logger.warning(f"Досягнуто ліміт кроків ({MAX_STEPS})")
        return {
            "messages": [AIMessage(content=f"⚠️ Досягнуто ліміт у {MAX_STEPS} кроків. "
                                           f"Надаю найкращу відповідь на основі зібраних даних.")],
            "step_count": step,
        }

    # Перевірка таймауту
    if elapsed > TIMEOUT_SEC:
        logger.warning(f"Перевищено таймаут ({TIMEOUT_SEC}с, пройшло {elapsed:.1f}с)")
        return {
            "messages": [AIMessage(content=f"⚠️ Перевищено таймаут ({TIMEOUT_SEC}с). "
                                           f"Завершую з наявними результатами.")],
            "step_count": step,
        }

    # Виклик LLM
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    t0 = time.time()
    response = llm_with_tools.invoke(messages)
    duration = time.time() - t0

    # Детекція повторів: той самий інструмент із тими самими аргументами двічі поспіль
    current_calls = []
    if response.tool_calls:
        current_calls = [(tc["name"], json.dumps(tc["args"], sort_keys=True))
                         for tc in response.tool_calls]
    prev_calls = state.get("last_tool_calls", [])
    if current_calls and current_calls == prev_calls:
        logger.warning("Виявлено повторний виклик інструмента — примусове завершення")
        return {
            "messages": [AIMessage(content="⚠️ Виявлено повторення дій. Завершую цикл.")],
            "step_count": step,
        }

    # Логування кроку в траєкторію (живе прямо в стані графа)
    traj = state.get("trajectory", [])
    traj.append({
        "step": step, "node": "agent", "duration_sec": round(duration, 3),
        "tool_calls": [tc["name"] for tc in (response.tool_calls or [])],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "messages": [response],
        "step_count": step,
        "start_time": start,
        "trajectory": traj,
        "last_tool_calls": current_calls,
    }


# Побудова захищеного графа
guarded_graph = StateGraph(GuardedState)
guarded_graph.add_node("agent", guarded_agent_node)
guarded_graph.add_node("tools", ToolNode(safe_tools))
guarded_graph.add_edge(START, "agent")
guarded_graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
guarded_graph.add_edge("tools", "agent")

guarded_agent = guarded_graph.compile()


def fresh_state(query: str, **overrides) -> dict:
    """Початковий стан для запуску захищеного агента."""
    state = {
        "messages": [HumanMessage(content=query)],
        "step_count": 0,
        "start_time": time.time(),
        "trajectory": [],
        "last_tool_calls": [],
    }
    state.update(overrides)
    return state


if __name__ == "__main__":
    # ── 1. Звичайний запуск: захист не спрацьовує ──
    print("=" * 60)
    print("📌 Демо 1: нормальний хід, захист мовчить")
    result = guarded_agent.invoke(
        fresh_state("Порахуй 2^10 + 3^5 та скажи, яка сьогодні дата")
    )
    print(f"✅ Результат: {get_text(result['messages'][-1].content)}")
    print(f"   Кроків: {result['step_count']}, траєкторія: {len(result['trajectory'])} записів")

    # ── 2. Ліміт кроків: підставляємо лічильник, який уже вичерпано ──
    print("\n" + "=" * 60)
    print("📌 Демо 2: спрацьовує max_steps")
    result = guarded_agent.invoke(
        fresh_state("Хто такий Тарас Шевченко?", step_count=MAX_STEPS)
    )
    print(f"🛑 {get_text(result['messages'][-1].content)}")

    # ── 3. Таймаут: підставляємо час старту у минулому ──
    print("\n" + "=" * 60)
    print("📌 Демо 3: спрацьовує timeout")
    result = guarded_agent.invoke(
        fresh_state("Хто такий Тарас Шевченко?", start_time=time.time() - TIMEOUT_SEC - 1)
    )
    print(f"🛑 {get_text(result['messages'][-1].content)}")

    # ── 4. Детекція повторів: кажемо агенту, що такий виклик уже був ──
    print("\n" + "=" * 60)
    print("📌 Демо 4: спрацьовує детекція повторів")
    already = [("calculator", json.dumps({"expression": "2+2"}, sort_keys=True))]
    result = guarded_agent.invoke(
        fresh_state("Порахуй 2+2", last_tool_calls=already)
    )
    print(f"🛑 {get_text(result['messages'][-1].content)}")

    print("\n✅ Демонстрацію захисних механізмів завершено.")
