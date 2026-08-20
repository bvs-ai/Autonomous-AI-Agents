"""m4 — той самий сервер, але по Streamable HTTP + найпростіша авторизація.

    python m4_http.py           # сервер + клієнт з токеном: усе працює
    python m4_http.py notoken   # той самий клієнт без токена: 401
    python m4_http.py serve     # тільки сервер, щоб постукати руками

stdio — це локальний підпроцес: один клієнт, ізоляція від ОС, авторизація не
потрібна. Щойно сервер став віддаленим, зʼявляється транспорт HTTP і разом з ним
питання «а хто це до нас прийшов». Тут — токен у заголовку; у проді на цьому
місці OAuth 2.1 (див. приклад 27 у lecture_examples).
"""
import asyncio
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from m1_server import mcp                      # той самий сервер, інший транспорт

URL = "http://127.0.0.1:8000/mcp"
TOKEN = "demo-token"


def serve():
    """Той самий сервер з m1, але доступний по мережі: http://127.0.0.1:8000/mcp.

    До нього тепер може підключитись будь-хто — звідси й перевірка токена нижче.
    """
    import uvicorn

    async def require_token(request, call_next):
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    app = mcp.streamable_http_app()          # веб-сервер замість mcp.run() (stdio)
    app.add_middleware(BaseHTTPMiddleware, dispatch=require_token)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


async def call_revenue(token: str | None):
    """Клієнт з m2, лише з іншим транспортом. Токен — єдина відмінність між режимами."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # у mcp>=1.29 заголовки/таймаути задаються на httpx-клієнті, а не в транспорті
    async with httpx.AsyncClient(headers=headers) as http:
        # Рівень 1 став HTTP; рівень 2 (ClientSession і все нижче) — дослівно як у m2.
        async with streamable_http_client(URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                out = await s.call_tool("revenue", {"region": "Захід", "quarter": "Q2"})
                print("revenue(Захід, Q2) =", out.content[0].text)


async def main(token: str | None):
    # Запускаємо MCP сервер окремим процесом
    server = await asyncio.create_subprocess_exec(
        sys.executable, __file__, "serve", stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.sleep(2)          # даємо серверу піднятися
        if server.returncode is not None:
            raise RuntimeError("сервер не піднявся — найімовірніше, порт 8000 вже зайнятий")
        await call_revenue(token)
    # 401 прилітає загорнутим у групу: усередині транспорту працює task group
    except* httpx.HTTPStatusError as group:
        print("відмова:", group.exceptions[0])
    finally:
        if server.returncode is None:
            server.terminate()
            await server.wait()


if __name__ == "__main__":
    mode = sys.argv[1:2]
    if mode == ["serve"]:
        serve()
    else:
        asyncio.run(main(None if mode == ["notoken"] else TOKEN))
