"""m4b — повний цикл проти ВІДДАЛЕНОГО сервера: агент + HTTP + токен.

    python m4b_agent_http.py          # піднімає сервер сам і проходить цикл
    python m4b_agent_http.py attach   # сервер уже запущено: python m4_http.py serve

Це m3, у якого змінили лише транспорт. Агент, load_mcp_tools() і create_agent()
не знають, по чому приїхали інструменти: рівень 2 (сесія) той самий, інший лише
рівень 1. Режим attach показує це найчесніше — сервер живе в іншому терміналі,
своїм життям, і клієнт до нього приходить як до чужого сервісу.

Цикл: handshake → discovery → рішення моделі → виклик по HTTP → відповідь.
"""
import asyncio
import sys

import httpx
from langchain.agents import create_agent
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from m4_http import TOKEN, URL          # адреса й токен ті самі, що в m4
from provider import make_llm

QUESTION = "Який регіон просів у Q2 порівняно з Q1 і на скільки відсотків?"


async def run_agent():
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        async with streamable_http_client(URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:   # рівень 2: як у m3
                await session.initialize()
                print("1. сесія з", URL, "встановлена")

                tools = await load_mcp_tools(session)
                print("2. discovery:", [t.name for t in tools], "\n")

                agent = create_agent(make_llm(), tools=tools)
                result = await agent.ainvoke({"messages": [("user", QUESTION)]})

    for m in result["messages"]:
        for call in getattr(m, "tool_calls", []):
            print(f"3. модель обрала {call['name']}({call['args']})")
        if m.type == "tool":
            print(f"4. відповідь сервера по HTTP: {m.text}")
    print("\n5. підсумок:", result["messages"][-1].text)


async def main(attach: bool):
    if attach:
        await run_agent()               # сервер підняли руками в іншому терміналі
        return

    server = await asyncio.create_subprocess_exec(
        sys.executable, "m4_http.py", "serve", stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.sleep(2)          # даємо серверу піднятися
        if server.returncode is not None:
            raise RuntimeError("сервер не піднявся — найімовірніше, порт 8000 вже зайнятий")
        await run_agent()
    finally:
        if server.returncode is None:
            server.terminate()
            await server.wait()


asyncio.run(main(attach=sys.argv[1:2] == ["attach"]))
