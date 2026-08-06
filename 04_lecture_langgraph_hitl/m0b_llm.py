"""m0 — найменший граф з живою моделлю: два вузли, один лінійний маршрут.

    classify -> respond

Модель підключена напряму через OpenAI SDK (без langchain-обгорток),
щоб було видно сирий виклик chat.completions.create.
Параметри виклику — у .env поруч зі скриптом:

    OPENAI_BASE_URL=...      # шлюз або https://api.openai.com/v1
    OPENAI_API_KEY=...
    LLM_MODEL=...
    LLM_TEMPERATURE=0        # необовʼязково, типово 0
    LLM_MAX_TOKENS=200       # необовʼязково, типово 200

    python m0_llm.py
    python m0_llm.py "Списати 50 000 грн на нового постачальника"
"""
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from openai import OpenAI
from langgraph.graph import END, START, StateGraph

load_dotenv()

MODEL = os.environ["LLM_MODEL"]
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "200"))

client = OpenAI()          # base_url і api_key SDK бере з OPENAI_* змінних


def ask(system: str, user: str) -> str:
    """Один виклик моделі. Уся робота з LLM у демо — тільки тут."""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    text = (resp.choices[0].message.content or "").strip()
    if not text:                    # reasoning-моделі інколи зʼїдають увесь бюджет
        raise RuntimeError(f"порожня відповідь, finish_reason="
                           f"{resp.choices[0].finish_reason} — підніміть LLM_MAX_TOKENS")
    return text


class State(TypedDict, total=False):
    request: str           # що просить користувач
    category: str          # висновок першого вузла
    answer: str            # висновок другого вузла


def classify(state: State) -> dict:
    category = ask(
        "Ти класифікатор заявок. Відповідай ОДНИМ словом: payment, access або other.",
        state["request"],
    )
    print(f"[node] classify -> {category}")
    return {"category": category}


def respond(state: State) -> dict:
    answer = ask(
        f"Заявку віднесено до категорії '{state['category']}'. "
        "Відповідай українською, максимум два речення.",
        state["request"],
    )
    print(f"[node] respond  -> {answer}")
    return {"answer": answer}


g = StateGraph(State)
g.add_node("classify", classify)
g.add_node("respond", respond)
g.add_edge(START, "classify")
g.add_edge("classify", "respond")
g.add_edge("respond", END)
graph = g.compile()        # без checkpointer: стан живе лише в памʼяті процесу

request = " ".join(sys.argv[1:]) or "Потрібно оплатити рахунок на 50 000 грн"
print(f"[model] {MODEL} | temperature={TEMPERATURE} | max_tokens={MAX_TOKENS}")
print(f"[input] {request}\n")

final = graph.invoke({"request": request})

print("\n[state] фінальний стан:")
for k, v in final.items():
    print(f"  {k:<9}: {v}")
