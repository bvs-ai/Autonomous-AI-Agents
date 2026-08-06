"""m1 — approval gate: interrupt() + SqliteSaver + Command(resume=...).

  python m1_approval.py start                 # дійти до interrupt і вийти
  python m1_approval.py state                 # що лежить у чекпойнті
  python m1_approval.py resume approve
  python m1_approval.py resume edit --set purpose=Узгоджено
  python m1_approval.py resume reject
"""
import json
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

DB = Path(__file__).parent / "m1.db"
CONFIG = {"configurable": {"thread_id": "demo"}}
EDITABLE = {"purpose"}          # allow-list: решту рев'юер правити не може

PAYMENT = {"action": "wire_transfer", "amount": 50_000, "currency": "UAH",
           "vendor": "ТОВ «Постачальник Плюс»", "purpose": "Договір №17"}


class State(TypedDict, total=False):
    action: dict
    decision: str


def analyze(state):
    print("[node] analyze: чернетка платежу", json.dumps(PAYMENT, ensure_ascii=False, indent=2, default=str))
    return {"action": PAYMENT}


def human_review(state):
    print("[node] human_review: старт (після resume виконається З ПОЧАТКУ)")
    answer = interrupt({"action": state["action"], "editable": sorted(EDITABLE)})
    print("[resume] відповідь людини:", answer)

    if answer["decision"] == "reject":
        return Command(update={"decision": "reject"}, goto=END)

    edits = {k: v for k, v in answer.get("edits", {}).items() if k in EDITABLE}
    ignored = set(answer.get("edits", {})) - EDITABLE
    if ignored:
        print("[state] поза allow-list, відхилено:", ignored)
    return Command(update={"action": {**state["action"], **edits},
                           "decision": answer["decision"]}, goto="execute")


def execute(state):
    a = state["action"]
    print(f"[node] execute: переказ {a['amount']} {a['currency']} -> {a['vendor']}")
    return {}


def app():
    g = StateGraph(State)
    g.add_node("analyze", analyze)
    g.add_node("human_review", human_review)
    g.add_node("execute", execute)
    g.set_entry_point("analyze")
    g.add_edge("analyze", "human_review")
    g.add_edge("execute", END)
    conn = sqlite3.connect(str(DB), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


cmd, *rest = sys.argv[1:] or ["start"]
graph = app()

if cmd == "start":
    DB.unlink(missing_ok=True)
    graph = app()
    result = graph.invoke({}, CONFIG)
    print("[interrupt] payload назовні:",
          json.dumps(result["__interrupt__"][0].value, ensure_ascii=False, indent=2, default=str))
    print(f"[checkpoint] стан у {DB.name} — процес можна завершити")

elif cmd == "state":
    snap = graph.get_state(CONFIG)
    print("[state] .next =", snap.next)
    print("[state] .values =", json.dumps(snap.values, ensure_ascii=False, indent=2, default=str))
    print("[state] чекає interrupt:", bool(snap.tasks and snap.tasks[0].interrupts))

elif cmd == "resume":
    decision = rest[0]
    edits = dict(kv.split("=", 1) for kv in rest if "=" in kv)   # усі FIELD=VALUE
    final = graph.invoke(Command(resume={"decision": decision, "edits": edits}), CONFIG)
    print("[state] фінальний decision:", final.get("decision"))
