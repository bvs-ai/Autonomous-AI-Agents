"""КРОК 4. Structured outputs та JSON-логування траєкторії.

Structured outputs гарантують, що відповідь LLM відповідає Pydantic-схемі —
без парсингу тексту регулярками. Саме на цьому тримається planner із Кроку 6.
Тут же — TrajectoryLogger, який пише повну траєкторію виконання у JSON.

Запуск:  .venv/bin/python step4_structured.py
"""
import json
from datetime import datetime, timezone
from typing import Optional, cast

from pydantic import BaseModel, Field

from step1_setup import llm, logger


# ── Structured output для планування ──
class PlanStep(BaseModel):
    """Один крок плану."""
    step_id: int = Field(..., description="Номер кроку (починаючи з 1)")
    description: str = Field(..., description="Опис дії", max_length=500)
    tool_name: Optional[str] = Field(None, description="Назва інструмента, якщо потрібен")


class Plan(BaseModel):
    """Структурований план виконання задачі."""
    goal: str = Field(..., description="Мета задачі")
    steps: list[PlanStep] = Field(..., description="Список кроків", min_length=1, max_length=15)
    reasoning: str = Field(..., description="Обґрунтування плану")


# ── JSON-логування траєкторії ──
class TrajectoryLogger:
    """Зберігає повну траєкторію виконання агента у JSON."""

    def __init__(self, log_path: str = "trajectory.json"):
        self.log_path = log_path
        self.entries = []

    def log_step(self, step_num: int, node: str, input_summary: str,
                 output_summary: str, duration_sec: float,
                 tool_name: Optional[str] = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step_num,
            "node": node,
            "tool": tool_name,
            "input": input_summary[:500],
            "output": output_summary[:500],
            "duration_sec": round(duration_sec, 3),
        }
        self.entries.append(entry)
        logger.info(f"Step {step_num} | {node} | {duration_sec:.2f}s | tool={tool_name}")

    def save(self):
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
        logger.info(f"Траєкторію збережено у {self.log_path} ({len(self.entries)} записів)")

    def summary(self) -> dict:
        total_time = sum(e["duration_sec"] for e in self.entries)
        tools_used = [e["tool"] for e in self.entries if e["tool"]]
        return {
            "total_steps": len(self.entries),
            "total_time_sec": round(total_time, 3),
            "tools_used": tools_used,
            "unique_tools": list(set(tools_used)),
        }


if __name__ == "__main__":
    # ВАЖЛИВО: для старих версій Gemini потрібно method="function_calling"
    # (JSON-режим на частині старих моделей віддає None замість об'єкта)
    structured_llm = llm.with_structured_output(Plan, method="json_schema")
    test_plan = structured_llm.invoke(
        "Склади план, щоб дізнатися населення п'яти найбільших міст України"
    )
    print(f"✅ Structured output працює. Мета: {test_plan.goal}")
    for s in test_plan.steps:
        print(f"   Крок {s.step_id}: {s.description} (tool: {s.tool_name})")
    # Крок «скласти остаточний список» іде без інструмента — саме тому
    # tool_name оголошено як Optional[str] = None.

    # ── Демонстрація логера траєкторії на реальному запуску ReAct-агента ──
    import time

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from step3_react import react_agent

    tl = TrajectoryLogger("trajectory.json")
    t0 = time.time()
    result = react_agent.invoke({"messages": [
        HumanMessage(content="Порахуй 2^10 + 3^5 і скажи, який сьогодні день тижня")
    ]})
    total = time.time() - t0

    step = 0
    for m in result["messages"]:
        step += 1
        if isinstance(m, AIMessage):
            tool_names = [tc["name"] for tc in (m.tool_calls or [])]
            tl.log_step(step, "agent", "", str(m.content),
                        total / len(result["messages"]),
                        tool_names[0] if tool_names else None)
        elif isinstance(m, ToolMessage):
            tl.log_step(step, "tools", "", str(m.content),
                        total / len(result["messages"]), m.name)
    tl.save()
    print("\n📊 Підсумок траєкторії:", json.dumps(tl.summary(), ensure_ascii=False))
