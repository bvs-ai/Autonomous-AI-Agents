"""m2 — checkpointer як fault-tolerance і time-travel.

  python m2_persistence.py crash        # падіння на execute, чекпойнти лишились
  python m2_persistence.py resume       # новий процес доводить до кінця
  python m2_persistence.py history      # всі чекпойнти thread'а
  python m2_persistence.py fork <id>    # гілка від старого чекпойнта
"""
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

DB = Path(__file__).parent / "m2.db"
CONFIG = {"configurable": {"thread_id": "pipeline"}}


class State(TypedDict, total=False):
    log: list
    crash: bool


def step(name):
    def node(state):
        print(f"[node] {name}")
        if name == "execute" and state.get("crash"):
            raise RuntimeError("сервер впав під час execute")
        return {"log": state.get("log", []) + [name]}
    return node


def app():
    g = StateGraph(State)
    for name in ("collect", "validate", "execute", "report"):
        g.add_node(name, step(name))
    g.set_entry_point("collect")
    g.add_edge("collect", "validate")
    g.add_edge("validate", "execute")
    g.add_edge("execute", "report")
    g.add_edge("report", END)
    conn = sqlite3.connect(str(DB), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


cmd, *rest = sys.argv[1:] or ["crash"]

if cmd == "crash":
    DB.unlink(missing_ok=True)
    try:
        app().invoke({"crash": True}, CONFIG)
    except RuntimeError as exc:
        print("[error]", exc)
        print("[checkpoint] collect/validate вже на диску — стан не втрачено")

elif cmd == "resume":
    graph = app()
    snap = graph.get_state(CONFIG)
    print("[state] .next =", snap.next, "| log =", snap.values.get("log"))
    graph.update_state(CONFIG, {"crash": False})          # "полагодили"
    print("[node] invoke(None, config) — без переісполнення collect/validate:")
    print("[state] фінальний log:", graph.invoke(None, CONFIG)["log"])

elif cmd == "history":
    for i, snap in enumerate(app().get_state_history(CONFIG)):
        print(f"#{i} id={snap.config['configurable']['checkpoint_id']} "
              f"next={snap.next} log={snap.values.get('log')}")

elif cmd == "fork":
    graph = app()
    at = {"configurable": {"thread_id": "pipeline", "checkpoint_ns": "", "checkpoint_id": rest[0]}}
    branch = graph.update_state(at, {"log": (graph.get_state(at).values.get("log") or []) + ["forked"],
                                     "crash": False})
    print("[state] received_state =", branch)
    print("[state] лог у гілці:", graph.invoke(None, branch)["log"])
