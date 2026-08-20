"""m2 — той самий діалог, що в m0, але через офіційний SDK.

    python m2_client.py

Різниця з m0 тільки в кількості рядків: handshake, id-шки та розбір відповідей
бере на себе ClientSession. Заразом дивимось на всі три примітиви й на те,
хто кожним керує: tool — модель, resource — застосунок, prompt — користувач.
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

params = StdioServerParameters(command=sys.executable, args=["m1_server.py"])


async def main():
    # Два рівні протоколу: транспорт окремо, семантика сесії окремо.
    async with stdio_client(params) as (read, write):     # рівень 1: транспорт (процес + 2 потоки)
        async with ClientSession(read, write) as s:       # рівень 2: сесія JSON-RPC поверх нього
            await s.initialize()                          # весь handshake з m0 — один рядок

            tools = await s.list_tools()
            print("tools    :", [t.name for t in tools.tools])

            res = await s.list_resources()
            print("resources:", [str(r.uri) for r in res.resources])

            pr = await s.list_prompts()
            print("prompts  :", [p.name for p in pr.prompts])

            # TOOL — дію обирає модель.
            out = await s.call_tool("compare_quarters", {"quarter_a": "Q1", "quarter_b": "Q2"})
            print("\ncompare_quarters(Q1, Q2) =", out.content[0].text)

            # RESOURCE — застосунок сам вирішує, що підкласти в контекст.
            data = await s.read_resource(AnyUrl("sales://schema"))
            print("sales://schema =", data.contents[0].text)

            # PROMPT — шаблон, який зі списку обирає користувач.
            p = await s.get_prompt("quarter_report", {"quarter": "Q2"})
            print("\nprompt quarter_report(Q2):\n ", p.messages[0].content.text)


asyncio.run(main())
