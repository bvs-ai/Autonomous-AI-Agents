"""m7, ЧАСТИНА 2 з 2 — агент-замовник на LangGraph, який делегує по A2A.

    python m7_worker_adk.py             # спершу, у терміналі 1
    python m7_coordinator_langgraph.py  # потім тут, у терміналі 2

Два агенти, два фреймворки, між ними — протокол:

    LangGraph (тут)  --A2A-->  Google ADK (m7_worker_adk.py)  --tool-->  дані

Жоден з них не знає, як влаштований інший. Спільне у них тільки Agent Card.
"""
import asyncio
import uuid

import httpx
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest
from langchain.agents import create_agent
from langchain_core.tools import tool

from provider import make_llm

WORKER = "http://127.0.0.1:8010"
QUESTION = "Дізнайся продажі Заходу за Q1 і за Q2 та скажи, чи є падіння."


@tool
async def ask_sales_agent(question: str) -> str:
    """Спитати віддаленого агента продажів. Питання — звичайним текстом."""
    print(f"   [A2A →] {question}")
    async with httpx.AsyncClient(timeout=120) as http:   # LLM на тому боці думає довго
        # create_client сам читає Agent Card і обирає транспорт — це і є SDK замість рук
        client = await create_client(WORKER, ClientConfig(httpx_client=http, streaming=False))

        request = SendMessageRequest()
        request.message.CopyFrom(Message(role=Role.ROLE_USER,
                                         message_id=uuid.uuid4().hex,
                                         parts=[Part(text=question)]))
        async for event in client.send_message(request):
            if event.task.artifacts:                       # Task дійшов до completed
                answer = event.task.artifacts[0].parts[0].text
                print(f"   [A2A ←] {answer}")
                return answer
    return "віддалений агент не відповів"


async def worker_is_up() -> bool:
    """Чи піднята частина 1? Питаємо за адресою Agent Card."""
    async with httpx.AsyncClient(timeout=2) as http:
        try:
            await http.get(f"{WORKER}/.well-known/agent-card.json")
            return True
        except httpx.HTTPError:
            return False


async def main():
    if not await worker_is_up():
        print("Немає звʼязку з агентом продажів.")
        print("Спершу запусти частину 1 в іншому терміналі:  python m7_worker_adk.py")
        return

    agent = create_agent(make_llm(), tools=[ask_sales_agent], system_prompt=(
        "Ти координатор. Сам цифр не знаєш — питай агента продажів через інструмент. "
        "Наприкінці дай коротку відповідь людині."))

    print(f"питання людини: {QUESTION}\n")
    result = await agent.ainvoke({"messages": [("user", QUESTION)]})
    print("\nвідповідь координатора:", result["messages"][-1].text)


asyncio.run(main())
