"""r3 — бюджети (кроки / токени / час) у графі.

  python r3_budget.py full      # бюджети просторі: агент сам доходить до мети (done)
  python r3_budget.py steps     # впирається в ліміт кроків
  python r3_budget.py tokens    # ліміт кроків є, але першим вичерпається токеновий
  python r3_budget.py time      # обидва ліміти цілі, але вийшов час

Два рівні таймаутів (asyncio.timeout на запит і на всю операцію) — у r3b_timeouts.py.

Бюджет живе в state ПЛОСКИМИ полями (current_step / tokens_used / started_at),
а BudgetController перестворюється з них на початку кожного вузла: LangGraph
серіалізує state чекпойнтером, мутабельний обʼєкт у стані ламається на
паралельних гілках. Патерн вузла: перевірка -> виконання -> реєстрація.
"""
import sys
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict
import operator

from langgraph.graph import END, StateGraph

MODE = (sys.argv[1:] or ["steps"])[0]
TARGET_SOURCES = 5               # скільки джерел агент вважає достатнім
LIMITS_BY_MODE = {               # ліміти конфігуровані, а не захардкоджені
    "full": {"max_steps": 10, "max_tokens": 100_000, "max_seconds": 300.0},
    "steps": {"max_steps": 3, "max_tokens": 100_000, "max_seconds": 300.0},
    "tokens": {"max_steps": 10, "max_tokens": 1_500, "max_seconds": 300.0},
    "time": {"max_steps": 10, "max_tokens": 100_000, "max_seconds": 0.55},
}


@dataclass
class BudgetController:
    """Три незалежні виміри. Один контролер на весь ланцюг, не на вузол."""
    max_steps: int
    max_tokens: int
    max_seconds: float
    current_step: int = 0
    tokens_used: int = 0
    started_at: float = 0.0

    def check(self) -> tuple[bool, str]:
        if self.current_step >= self.max_steps:
            return False, f"кроки: {self.current_step}/{self.max_steps}"
        if self.tokens_used >= self.max_tokens:
            return False, f"токени: {self.tokens_used}/{self.max_tokens}"
        elapsed = time.monotonic() - self.started_at
        if elapsed >= self.max_seconds:
            return False, f"час: {elapsed:.2f}s/{self.max_seconds}s"
        return True, ""


class State(TypedDict, total=False):
    current_step: int
    tokens_used: int
    started_at: float
    findings: Annotated[list, operator.add]
    status: str
    stop_reason: str


def agent_step(state: State) -> dict:
    budget = BudgetController(**LIMITS,                       # <-- перестворили з плоских полів
                              current_step=state.get("current_step", 0),
                              tokens_used=state.get("tokens_used", 0),
                              started_at=state.get("started_at") or time.monotonic())

    ok, reason = budget.check()                               # 1. перевірка
    if not ok:
        print(f"[budget] вичерпано -> {reason}")
        return {"status": "degraded", "stop_reason": reason}

    n = budget.current_step + 1                               # 2. виконання
    time.sleep(0.15)
    fact = f"джерело #{n}: постачальник має {n * 4} закритих договорів"
    print(f"[крок {n}] {fact}")

    return {"findings": [fact],                               # 3. реєстрація витрат
            "current_step": n,
            "tokens_used": budget.tokens_used + 1_000,
            "started_at": budget.started_at,
            "status": "done" if n >= TARGET_SOURCES else "running"}


def report(state: State) -> dict:
    findings = state.get("findings", [])
    status = state.get("status", "degraded")      # ключі NotRequired: дефолт песимістичний
    started_at = state.get("started_at") or time.monotonic()
    print(f"\n[report] статус: {status}")
    if status == "degraded":
        print(f"[report] причина зупинки: {state.get('stop_reason', 'невідома')}")
        print(f"[report] ЧАСТКОВИЙ результат ({len(findings)} з невідомої кількості):")
    else:
        print(f"[report] ПОВНИЙ результат: зібрано {len(findings)} з {TARGET_SOURCES} джерел")
    for f in findings:
        print("   -", f)
    print("[report] витрачено:", state.get("current_step"), "кроків,",
          state.get("tokens_used"), "токенів,",
          f"{time.monotonic() - started_at:.2f}s")
    return {}


def route(state: State) -> str:
    return "report" if state.get("status") in ("degraded", "done") else "agent_step"


if MODE not in LIMITS_BY_MODE:   # режим із CLI, тому перевіряємо явно
    raise SystemExit(f"невідомий режим: {MODE!r}. Доступні: {', '.join(LIMITS_BY_MODE)}")

LIMITS = LIMITS_BY_MODE[MODE]
print(f"[режим] {MODE}: {LIMITS}\n")
g = StateGraph(State)
g.add_node("agent_step", agent_step)
g.add_node("report", report)
g.set_entry_point("agent_step")
g.add_conditional_edges("agent_step", route, {"agent_step": "agent_step", "report": "report"})
g.add_edge("report", END)
g.compile().invoke({"started_at": time.monotonic()}, {"recursion_limit": 50})
