"""m4 — паралельність: Send fan-out, reducer на результатах, RetryPolicy.

  python m4_parallel.py fail       # гілка падає: merge не виконано, next=('fetch',)
  python m4_parallel.py degrade    # виняток оброблено в вузлі -> звіт з діркою
  python m4_parallel.py retry      # RetryPolicy: ретраїться ЛИШЕ гілка, що впала
"""
import operator
import sqlite3
import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy, Send

MODE = (sys.argv[1:] or ["fail"])[0]
DB = Path(__file__).parent / "m4.db"
SOURCES = ["erp", "bank", "contracts", "sanctions"]
attempts = 0


class State(TypedDict, total=False):
    # без operator.add паралельні гілки затирали б результати одна одної
    results: Annotated[list, operator.add]
    report: dict


def plan(state):
    return {"results": []}


def fan_out(state):
    return [Send("fetch", {"source": s}) for s in SOURCES]   # N гілок в одному superstep


def fetch(payload):
    global attempts
    source = payload["source"]
    time.sleep(0.1)
    if source == "sanctions":
        if MODE == "fail":
            raise ConnectionError("sanctions API timeout")       # без обробки
        if MODE == "degrade":
            print("[branch] sanctions -> unavailable (локальна деградація)")
            return {"results": [{"source": source, "status": "unavailable"}]}
        attempts += 1
        print(f"[retry] sanctions: спроба #{attempts}")
        if attempts < 3:
            raise ConnectionError("sanctions API timeout")       # RetryPolicy підхопить
    print(f"[branch] {source} -> ok")
    return {"results": [{"source": source, "status": "ok"}]}


def merge(state):
    results = sorted(state["results"], key=lambda r: r["source"])   # порядок гілок не гарантований
    holes = [r["source"] for r in results if r["status"] != "ok"]
    return {"report": {"sources": len(results), "holes": holes}}


g = StateGraph(State)
g.add_node("plan", plan)
# retry_policy тільки в режимі retry — інакше падіння в `fail` теж ретраїлось би
g.add_node("fetch", fetch,
           retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.05) if MODE == "retry" else None)
g.add_node("merge", merge)
g.set_entry_point("plan")
g.add_conditional_edges("plan", fan_out, ["fetch"])
g.add_edge("fetch", "merge")
g.add_edge("merge", END)

DB.unlink(missing_ok=True)
conn = sqlite3.connect(str(DB), check_same_thread=False)
graph = g.compile(checkpointer=SqliteSaver(conn))
config = {"configurable": {"thread_id": MODE}}

try:
    final = graph.invoke({}, config)
    print("[merge] звіт:", final["report"])
except Exception as exc:  # noqa: BLE001 — демо: ловимо будь-яке падіння вузла
    snap = graph.get_state(config)
    print("[error] invoke кинув:", repr(exc))
    print("[state] pending writes успішних гілок:", snap.values.get("results"))
    print("[state] next =", snap.next, "-> superstep НЕ закомічено, merge не виконано")
    print("[state] повторний invoke перевиконає ЛИШЕ гілку, що впала:")
    try:
        graph.invoke(None, config)
    except Exception as exc2:  # noqa: BLE001 — демо: показуємо повторний збій
        print("[error]", repr(exc2))
