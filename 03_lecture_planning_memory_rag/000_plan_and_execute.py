"""
Практика 1 — ПЛАНУВАННЯ: plan-and-execute «у відкриту».

Ідея: LLM повертає МАШИНОЧИТНИЙ план (JSON зі списком кроків: tool + args),
а простий executor виконує кроки локальними інструментами — з бюджетом і stop_reason.
Нічого не приховано: друкуємо ціль, план і кожне спостереження.

  planner (LLM)  ->  [ {tool, args}, ... ]  ->  executor (наш код) -> результат

Запуск:  python 001_plan_and_execute.py   (потрібен .env, див. .env.example)
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
MODEL = os.environ.get("LLM_MODEL", "kr/claude-haiku-4.5")


def call_llm(messages):
    r = requests.post(
        f"{os.environ['OPENAI_BASE_URL']}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": MODEL, "stream": False, "messages": messages},
    )
    return r.json()["choices"][0]["message"]["content"]


# ── Локальні інструменти (без LLM). Executor викликає їх за іменем ──
ORDERS = [
    {"id": "A-1001", "status": "повернення", "sum": 1200},
    {"id": "A-1002", "status": "повернення", "sum": 300},
    {"id": "A-1003", "status": "доставлено", "sum": 900},
    {"id": "A-1004", "status": "повернення", "sum": 5000},
]
LAST = {"value": None}  # вихід попереднього кроку (простий dataflow)


def search_orders(args):
    return [o for o in ORDERS if o["status"] == args.get("status")]


def sum_field(args):
    items = LAST["value"] or []
    return sum(o.get(args.get("field", "sum"), 0) for o in items)


TOOLS = {"search_orders": search_orders, "sum_field": sum_field}
CATALOG = (
    "- search_orders(status: 'повернення'|'доставлено') -> список замовлень\n"
    "- sum_field(field: str) -> сума поля по замовленнях з ПОПЕРЕДНЬОГО кроку"
)
MAX_STEPS = 5  # бюджет плану


def make_plan(objective):
    text = call_llm([
        {"role": "system", "content":
            "Ти планувальник. Розклади ціль на послідовні кроки.\n"
            'Поверни СТРОГО JSON: {"steps":[{"tool":"...","args":{...}}]}.\n'
            "Доступні інструменти:\n" + CATALOG},
        {"role": "user", "content": objective},
    ]).strip().strip("`")
    if text.startswith("json"):
        text = text[4:]
    return json.loads(text)["steps"]


def run_plan(steps):
    if len(steps) > MAX_STEPS:
        print(f"[BUDGET] кроків {len(steps)} > ліміт {MAX_STEPS} → stop")
        return "max_steps"
    for i, step in enumerate(steps, 1):
        tool, args = step.get("tool"), step.get("args", {})
        print(f"[STEP {i}] {tool}({args})")
        if tool not in TOOLS:
            print(f"[STOP] невідомий інструмент: {tool}")
            return "unknown_tool"
        LAST["value"] = TOOLS[tool](args)
        print(f"[OBSERVE] {LAST['value']}")
    return "done"


if __name__ == "__main__":
    objective = "Порахуй сумарну вартість усіх замовлень, що зараз на поверненні."
    print(f"[GOAL] {objective}\n")

    steps = make_plan(objective)
    print(f"[PLAN]\n{json.dumps(steps, ensure_ascii=False, indent=2)}\n")

    reason = run_plan(steps)
    print(f"\n[RESULT] stop_reason={reason} | підсумок={LAST['value']}")

    # ── Твоя черга ──
    # 1) Додай інструмент count_orders і ціль «скільки повернень і на яку суму».
    # 2) Постав MAX_STEPS = 1 — побач, як спрацює бюджет (stop_reason=max_steps).
