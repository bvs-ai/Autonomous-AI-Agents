"""m3 — MCP-сервер як інструменти LangGraph-агента (потрібен ключ у .env).

    python m3_agent.py

Три рядки клею: підключились до сервера → load_mcp_tools() перетворив MCP-tools
на LangChain-tools → create_agent() зібрав агента. Агент сам вирішує, який
інструмент викликати; єдине, на що він при цьому спирається, — докстрінги з m1.
"""
import asyncio
import sys

from langchain.agents import create_agent
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from provider import make_llm

QUESTION = "Який регіон просів у Q2 порівняно з Q1 і на скільки відсотків?"
params = StdioServerParameters(command=sys.executable, args=["m1_server.py"])


async def main():
    async with stdio_client(params) as (read, write):        # рівень 1: транспорт
        async with ClientSession(read, write) as session:    # рівень 2: сесія JSON-RPC
            await session.initialize()
            tools = await load_mcp_tools(session)
            print("MCP-tools у вигляді LangChain-tools:", [t.name for t in tools], "\n")

            agent = create_agent(make_llm(), tools=tools)
            result = await agent.ainvoke({"messages": [("user", QUESTION)]})

            for m in result["messages"]:
                for call in getattr(m, "tool_calls", []):
                    print(f"→ виклик {call['name']}({call['args']})")
                if m.type == "tool":
                    print(f"← {m.text}")
            print("\nВідповідь:", result["messages"][-1].text)


asyncio.run(main())
