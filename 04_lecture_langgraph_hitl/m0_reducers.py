"""m0 — reducer визначає семантику каналу.

Три канали, одне й те саме оновлення двічі, три різні результати.
"""
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


def versioned(current: list, update: list) -> list:
    """Накопичуємо, але кожна правка одразу отримує номер версії."""
    current = current or []
    return current + [f"v{len(current) + 1}: {u}" for u in update]


class State(TypedDict):
    plain: list                              # без reducer  -> перезапис
    history: Annotated[list, operator.add]   # -> накопичення
    chat: Annotated[list, add_messages]      # -> оновлення по id
    draft: Annotated[list, versioned]        # -> свій reducer: нумерація версій


def agent(state):
    return {"plain": ["чернетка"],
            "history": ["чернетка"],
            "chat": [AIMessage(content="чернетка", id="msg-1")],
            "draft": ["чернетка"]}


def human_edit(state):
    return {"plain": ["правка людини"],
            "history": ["правка людини"],
            "chat": [AIMessage(content="правка людини", id="msg-1")],
            "draft": ["правка людини"]}


g = StateGraph(State)
g.add_node("agent", agent)
g.add_node("human_edit", human_edit)
g.add_edge(START, "agent")
g.add_edge("agent", "human_edit")
g.add_edge("human_edit", END)

final = g.compile().invoke({"plain": [], "history": [], "chat": [], "draft": []})

print("plain   (без reducer) :", final["plain"], "<- друге затерло перше")
print("history (operator.add):", final["history"], "<- ДУБЛЬ замість правки")
print("chat    (add_messages):", [(m.id, m.content) for m in final["chat"]],
      "<- msg-1 оновлено на місці")
print("draft   (свій reducer):", final["draft"], "<- кожна правка з номером версії")
