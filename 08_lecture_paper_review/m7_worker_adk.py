"""m7, ЧАСТИНА 1 з 2 — агент-виконавець на Google ADK, виставлений по A2A.

    python m7_worker_adk.py        # цей термінал залишається зайнятим

Це сервер: піднімається й мовчки чекає. Питання йому ставить частина 2 —
m7_coordinator_langgraph.py, її треба запустити в ІНШОМУ терміналі.
"""
import os

from dotenv import load_dotenv
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import LlmAgent

load_dotenv(".env")

SALES = {("Захід", "Q1"): 1500, ("Захід", "Q2"): 870,
         ("Північ", "Q1"): 1200, ("Північ", "Q2"): 1310}


def revenue(region: str, quarter: str) -> int:
    """Продажі регіону за квартал, тис. грн."""
    return SALES.get((region, quarter), -1)


agent = LlmAgent(
    name="sales_agent",
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    description="Знає цифри продажів по регіонах і кварталах",
    instruction="Ти аналітик продажів. Відповідай коротко, цифрами з інструмента revenue.",
    tools=[revenue],
)

app = to_a2a(agent, port=8010)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8010, log_level="warning")
