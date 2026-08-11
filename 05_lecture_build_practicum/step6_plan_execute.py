"""КРОК 6. Plan-and-Execute: planner → executor → replanner.

Три вузли:
  planner   — будує план через structured outputs (Pydantic-модель Plan);
  executor  — виконує поточний крок плану ВКЛАДЕНИМ ReAct-агентом із Кроку 3;
  replanner — дивиться на результати і вирішує: continue / replan / finish.

Запуск:  .venv/bin/python step6_plan_execute.py
"""
from typing import Annotated, Literal, Optional, TypedDict, cast

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from step1_setup import get_text, llm, logger
from step3_react import react_agent
from step4_structured import Plan


# ── Стан Plan-and-Execute ──
class PlanExecuteState(TypedDict):
    messages: Annotated[list, add_messages]
    task: str                    # вхідне завдання
    plan: list[str]              # поточний план (список описів кроків)
    completed_steps: list[str]   # результати виконаних кроків
    current_step_idx: int        # індекс поточного кроку
    response: str                # фінальна відповідь
    replan_count: int            # лічильник переплановувань


# ── Structured output для replanner ──
class ReplanDecision(BaseModel):
    """Рішення replanner-а."""
    action: Literal["continue", "replan", "finish"] = Field(
        ..., description="continue=виконувати наступний крок, "
                         "replan=переплановувати, finish=завершити"
    )
    updated_plan: Optional[list[str]] = Field(
        None, description="Новий план (якщо action='replan')"
    )
    final_answer: Optional[str] = Field(
        None, description="Фінальна відповідь (якщо action='finish')"
    )
    reasoning: str = Field(..., description="Обґрунтування рішення")


def planner_node(state: PlanExecuteState) -> dict:
    """Генерує план для задачі."""
    task = state["task"]
    structured_planner = llm.with_structured_output(Plan, method="json_schema")

    # Retry-логіка: Gemini іноді повертає None замість об'єкта
    plan_obj = None
    for attempt in range(3):
        # cast — підказка редактору: with_structured_output типізовано як
        # `dict | BaseModel`, а Optional тут не зайвий — Gemini справді буває None.
        plan_obj = structured_planner.invoke(
            f"Склади покроковий план для виконання задачі: {task}. "
            f"Кожен крок має бути конкретною дією, яку можна виконати за допомогою "
            f"інструментів: calculator, current_datetime, wikipedia_search, http_get. "
            f"Не більше 4 кроків."
        )
        if plan_obj is not None and plan_obj.steps:
            break
        logger.warning(f"Planner: спроба {attempt+1}/3 — отримано порожню відповідь, повтор...")

    if plan_obj is None or not plan_obj.steps:
        # Fallback: простий однокроковий план
        logger.error("Planner: не вдалося згенерувати план, використовуємо fallback")
        return {"plan": [task], "current_step_idx": 0, "completed_steps": [], "replan_count": 0}

    steps = [s.description for s in plan_obj.steps]
    logger.info(f"Planner: створено план із {len(steps)} кроків для '{task}'")
    for i, s in enumerate(steps, 1):
        print(f"   📋 Крок {i}: {s}")
    return {"plan": steps, "current_step_idx": 0, "completed_steps": [], "replan_count": 0}


def executor_node(state: PlanExecuteState) -> dict:
    """Виконує поточний крок плану за допомогою ReAct-агента."""
    idx = state["current_step_idx"]
    plan = state["plan"]

    if idx >= len(plan):
        return {"response": "Усі кроки плану виконано."}

    step_desc = plan[idx]
    context = ""
    if state["completed_steps"]:
        context = "\nПопередні результати:\n" + "\n".join(
            f"- Крок {i+1}: {r}" for i, r in enumerate(state["completed_steps"])
        )

    prompt = (
        f"Виконай наступний крок: {step_desc}\n"
        f"Це крок {idx+1} з {len(plan)} загального плану.{context}\n"
        f"Використовуй інструменти за потребою. Поверни стислий результат."
    )

    # Вкладений виклик ReAct-агента — executor сам є повноцінним агентом
    result = react_agent.invoke({"messages": [HumanMessage(content=prompt)]})
    step_result = get_text(result["messages"][-1].content)
    logger.info(f"Executor: крок {idx+1} — {step_result[:100]}...")

    completed = state["completed_steps"] + [step_result]
    return {"completed_steps": completed, "current_step_idx": idx + 1}


def replanner_node(state: PlanExecuteState) -> dict:
    """Оцінює прогрес і вирішує: продовжити, переплановувати чи завершити."""
    structured_replanner = llm.with_structured_output(ReplanDecision, method="json_schema")

    completed_summary = "\n".join(
        f"Крок {i+1}: {r}" for i, r in enumerate(state["completed_steps"])
    )
    remaining = state["plan"][state["current_step_idx"]:]
    remaining_summary = "\n".join(
        f"Крок {i}: {s}" for i, s in enumerate(remaining, state["current_step_idx"] + 1)
    )

    decision = None
    for attempt in range(3):
        decision = structured_replanner.invoke(
            f"Завдання: {state['task']}\n\n"
            f"Виконані кроки:\n{completed_summary}\n\n"
            f"Залишились кроки:\n{remaining_summary or '(немає)'}\n\n"
            f"Вирішуй: якщо завдання виконано — 'finish' (обов'язково вкажи final_answer); "
            f"якщо план треба змінити — 'replan'; якщо все ок — 'continue'."
        )
        if decision is not None:
            break
        logger.warning(f"Replanner: спроба {attempt+1}/3 — порожня відповідь, повтор...")

    if decision is None:
        # Fallback: якщо залишились кроки — continue, інакше — finish
        if remaining:
            return {}
        return {"response": "Завдання виконано (replanner не відповів)."}

    logger.info(f"Replanner: {decision.action} — {decision.reasoning[:80]}...")

    if decision.action == "finish":
        return {"response": decision.final_answer or "Завдання виконано."}
    elif decision.action == "replan" and decision.updated_plan:
        return {
            "plan": decision.updated_plan,
            "current_step_idx": 0,
            "completed_steps": state["completed_steps"],
            "replan_count": state.get("replan_count", 0) + 1,
        }
    else:
        return {}


def should_continue(state: PlanExecuteState) -> str:
    """Визначає наступний вузол після replanner."""
    if state.get("response"):
        return "finish"
    if state.get("replan_count", 0) > 3:
        return "finish"  # захист від нескінченного переплановування
    if state["current_step_idx"] >= len(state["plan"]):
        return "finish"
    return "execute"


pe_graph = StateGraph(PlanExecuteState)
pe_graph.add_node("planner", planner_node)
pe_graph.add_node("executor", executor_node)
pe_graph.add_node("replanner", replanner_node)

pe_graph.add_edge(START, "planner")
pe_graph.add_edge("planner", "executor")
pe_graph.add_edge("executor", "replanner")
pe_graph.add_conditional_edges(
    "replanner",
    should_continue,
    {"execute": "executor", "finish": END}
)

pe_agent = pe_graph.compile()


def new_pe_state(task: str) -> dict:
    """Початковий стан Plan-and-Execute."""
    return {
        "task": task, "messages": [], "plan": [], "completed_steps": [],
        "current_step_idx": 0, "response": "", "replan_count": 0,
    }


if __name__ == "__main__":
    print("✅ Plan-and-Execute граф скомпільовано.")

    result = pe_agent.invoke(new_pe_state(
        "Дізнайся поточну дату, порахуй скільки днів у цьому місяці, і знайди в Wikipedia, "
        "яка подія сталася в цей день в історії."
    ))
    print(f"\n📋 Фінальна відповідь:\n{result.get('response', 'N/A')}")
    print(f"   Виконано кроків: {len(result.get('completed_steps', []))}")
    print(f"   Переплановувань: {result.get('replan_count', 0)}")

    print("\n📈 Схема графа (Mermaid):")
    print(pe_agent.get_graph().draw_mermaid())
