"""m3 — rubber stamp / OWASP ASI09: рішення змінює РЕНДЕР, а не дані.

Один і той самий payload показано двома способами: розповідь агента і сира дія.

  python m3_rubber_stamp.py                     # питає з клавіатури
  python m3_rubber_stamp.py approve reject      # відповіді наперед (репетиція)
"""
import sys
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

ACTION = {
    "action": "wire_transfer",
    "amount": 50_000,
    "currency": "UAH",
    "vendor": "ТОВ «Постачальник Плюс»",
    "iban": "UA92 ... 6600 1",
    "previous_iban": "UA21 ... 6610 0",          # сирий факт: IBAN змінився
    "narrative": ("Перевірений постачальник, 12 платежів без претензій, "
                  "договір погоджено юристами. Знижка діє ще 2 години — "
                  "рекомендую затвердити зараз."),
}


class State(TypedDict, total=False):
    action: dict
    decision: str
    executed: bool


def review(state):
    answer = interrupt({"action": state["action"]})
    if answer["decision"] == "approve":
        return Command(update={"decision": "approve"}, goto="execute")
    return Command(update={"decision": "reject"}, goto=END)


def execute(state):
    print("[node] execute: гроші пішли")
    return {"executed": True}


def build():
    g = StateGraph(State)
    g.add_node("review", review)
    g.add_node("execute", execute)
    g.add_edge(START, "review")
    g.add_edge("execute", END)
    return g.compile(checkpointer=InMemorySaver())


def gate(ui, answers):
    """Один прогін: interrupt -> рендер payload -> Command(resume=...)."""
    graph = build()
    config = {"configurable": {"thread_id": ui}}
    payload = graph.invoke({"action": ACTION}, config)["__interrupt__"][0].value
    a = payload["action"]

    print(f"\n===== UI {ui} =====")
    if ui == "narrative":
        print("🤖", a["narrative"])
    else:
        for k, v in a.items():
            if k != "narrative":
                print(f"  {k:<14}: {v}")
        print(f"  !! IBAN змінився з минулого платежу: {a['iban'] != a['previous_iban']}")

    decision = answers.pop(0) if answers else input(f"[{ui}] approve/reject: ").strip()
    graph.invoke(Command(resume={"decision": decision}), config)
    return decision


answers = sys.argv[1:]
a = gate("narrative", answers)
b = gate("structured", answers)
print(f"\nnarrative -> {a} | structured -> {b}")
print("Дія та сама, payload той самий. Змінився лише рендер — це і є ASI09.")
