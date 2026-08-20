"""m5 — A2A: Agent Card, Task, multi-turn. Сервер і клієнт в одному файлі.

    python m5_a2a.py            # клієнт сам піднімає сервер підпроцесом
    python m5_a2a.py serve      # тільки сервер, якщо хочеться постукати curl-ом

A2A — це теж JSON-RPC, тільки по HTTP і між агентами, а не між агентом і
ресурсом. Дві відмінності від MCP видно прямо у виводі:
  1. discovery через Agent Card за фіксованою адресою (не tools/list);
  2. Task живе між запитами: у нього є id, статус і стан input-required,
     коли агент просить уточнення. MCP tool call такого не вміє — він
     закінчується разом з відповіддю.

Усередині цей агент ходить у MCP-сервер з m1 — обидва протоколи в одному кадрі.
"""
import asyncio
import re
import sys
import uuid

import httpx
from fastapi import FastAPI, Request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PORT = 8001
BASE = f"http://127.0.0.1:{PORT}"

CARD = {
    "name": "Sales Analytics Agent",
    "description": "Порівнює квартали по регіонах і повертає короткий звіт",
    "url": BASE,
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [{"id": "quarter_report", "name": "Quarter report",
                "description": "Звіт про зміну продажів між двома кварталами",
                "inputModes": ["text"], "outputModes": ["text"]}],
}

# ── Сервер ───────────────────────────────────────────────────────────────────
app = FastAPI()
TASKS: dict[str, dict] = {}      # стан задач живе між запитами — саме цим Task і відрізняється
                                 # від MCP tool call, який помирає разом з відповіддю


@app.get("/.well-known/agent-card.json")   # адреса зафіксована специфікацією
def agent_card():
    return CARD


@app.post("/")                             # у JSON-RPC один URL на всі методи:
async def rpc(request: Request):           # що саме робити, написано в тілі запиту
    body = await request.json()
    method, params = body["method"], body["params"]

    # tasks/get — другий і останній метод, який розуміє це демо: віддати задачу як є
    if method == "tasks/get":
        return {"jsonrpc": "2.0", "id": body["id"], "result": TASKS[params["id"]]}

    # метод a2a — message/send. Є taskId у повідомленні → продовження наявної задачі, немає → нова
    text = params["message"]["parts"][0]["text"]
    task = TASKS.get(params["message"].get("taskId"))
    if task is None:
        task = {"id": uuid.uuid4().hex[:8], "status": {"state": "submitted"}, "artifacts": []}
        TASKS[task["id"]] = task

    quarters = re.findall(r"Q[1-4]", text)               # замість LLM: демо розбирає текст регуляркою
    if len(quarters) < 2:
        # Агенту бракує вхідних даних — це штатний стан Task, а не помилка.
        task["status"] = {"state": "input-required",
                          "message": "Які саме квартали порівняти? Наприклад: Q1 і Q2"}
    else:
        task["status"] = {"state": "submitted"}
        asyncio.create_task(work(task, *quarters[:2]))   # довга робота у фоні
    # Відповідь — це дескриптор задачі, а не результат: роботу ще навіть не почато
    return {"jsonrpc": "2.0", "id": body["id"], "result": task}


async def work(task: dict, qa: str, qb: str):
    """Фонова робота: клієнт про її перебіг дізнається лише опитуванням tasks/get."""
    task["status"] = {"state": "working"}
    await asyncio.sleep(1.5)                              # імітація довгої роботи
    params = StdioServerParameters(command=sys.executable, args=["m1_server.py"])
    async with stdio_client(params) as (read, write):     # ← а тут уже MCP
        async with ClientSession(read, write) as s:       # рівень 2: сесія JSON-RPC
            await s.initialize()
            out = await s.call_tool("compare_quarters", {"quarter_a": qa, "quarter_b": qb})
    task["artifacts"] = [{"name": "report",
                          "parts": [{"kind": "text", "text": f"{qa} → {qb}: {out.content[0].text}"}]}]
    task["status"] = {"state": "completed"}


# ── Клієнт ───────────────────────────────────────────────────────────────────
async def send(http: httpx.AsyncClient, text: str, task_id: str | None = None) -> dict:
    """Одна операція і на перше звернення, і на уточнення — різниця тільки в taskId."""
    message = {"role": "user", "parts": [{"kind": "text", "text": text}]}
    if task_id:
        message["taskId"] = task_id                       # продовжуємо ТУ САМУ задачу
    r = await http.post(BASE, json={"jsonrpc": "2.0", "id": 1,       # id запиту JSON-RPC,
                                    "method": "message/send",        # не плутати з id задачі
                                    "params": {"message": message}})
    return r.json()["result"]


async def client():
    async with httpx.AsyncClient(timeout=10) as http:
        # Discovery по-A2A: не питаємо агента про вміння, а читаємо картку за фіксованою адресою
        card = (await http.get(f"{BASE}/.well-known/agent-card.json")).json()
        print(f"Agent Card: {card['name']} | скіли: {[s['id'] for s in card['skills']]}\n")

        # Перше звернення: без taskId, тому сервер заведе нову задачу
        task = await send(http, "Зроби звіт по продажах")
        print(f"task {task['id']}: {task['status']['state']} — {task['status']['message']}")

        # Відповідаємо на уточнення "Які саме квартали порівняти?" — з тим самим taskId,
        # тому це ТА САМА задача, а не нова. Питання й відповідь захардкоджені для наочності
        # (у житті тут була б розмова з користувачем або з іншим агентом)
        task = await send(http, "Порівняй Q1 і Q2", task_id=task["id"])
        state = task["status"]["state"]
        print(f"task {task['id']}: {state}")
        while state != "completed":                       # polling; у справжньому A2A є ще stream
            await asyncio.sleep(0.5)
            r = await http.post(BASE, json={"jsonrpc": "2.0", "id": 2, "method": "tasks/get",
                                            "params": {"id": task["id"]}})
            task = r.json()["result"]
            if task["status"]["state"] != state:
                state = task["status"]["state"]
                print(f"task {task['id']}: {state}")
        # Результат лежить в artifacts задачі, а не в тілі відповіді на message/send
        print("\nartifact:", task["artifacts"][0]["parts"][0]["text"])


async def main():
    # Запускаємо A2A сервер окремим процесом: python m5_a2a.py serve
    server = await asyncio.create_subprocess_exec(sys.executable, __file__, "serve")
    try:
        await asyncio.sleep(2)                        # даємо серверу піднятися
        if server.returncode is not None:             # сервер не піднявся — далі немає сенсу
            raise SystemExit(f"сервер не стартував (код {server.returncode}), див. лог вище")
        # Передаємо управління клієнту в цьому процесі
        await client()
    finally:
        if server.returncode is None:
            server.terminate()
        await server.wait()                           # звільнити порт до виходу зі скрипта


if __name__ == "__main__":
    # Один файл, дві ролі: із "serve" це агент-виконавець, без аргументів — його клієнт
    if sys.argv[1:2] == ["serve"]:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    else:
        asyncio.run(main())
