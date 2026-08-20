"""m0 — MCP без SDK: сирий JSON-RPC 2.0 по stdio.

    python m0_protocol.py

Піднімає m1_server.py як звичайний підпроцес і сам пише йому в stdin рядки JSON.
Ніякої магії в протоколі немає: один рядок = одне повідомлення.
`→` це те, що пише клієнт, `←` те, що відповідає сервер.
"""
import json
import subprocess
import sys

PROTO = "2025-06-18"


# Рівень 2 (сесія): кадрування, id, розбір відповіді — усе, що далі робить ClientSession.
def send(proc, msg):
    print("─" * 78)
    print("→", json.dumps(msg, ensure_ascii=False), "\n")
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None                      # нотифікація: відповіді не буде
    line = proc.stdout.readline()
    print("←", line.strip(), "\n")
    return json.loads(line)


# Рівень 1 (транспорт) руками: процес + stdin/stdout; те саме, що потім дає stdio_client.
server = subprocess.Popen([sys.executable, "m1_server.py"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,   # сервер логує у stderr, нам він тут заважає
                          text=True, bufsize=1)
try:
    # 1. Handshake: домовляємось про версію протоколу і хто що вміє.
    send(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": PROTO, "capabilities": {},
                             "clientInfo": {"name": "m0", "version": "0"}}})
    send(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # 2. Discovery: що взагалі вміє цей сервер.
    send(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    # 3. Виклик інструмента.
    send(server, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "revenue",
                             "arguments": {"region": "Захід", "quarter": "Q2"}}})

    # 4. Помилка — теж штатна відповідь протоколу, а не падіння зʼєднання.
    send(server, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                  "params": {"name": "revenue",
                             "arguments": {"region": "Марс", "quarter": "Q2"}}})

    # 5. Resource читається іншим методом, ніж tool.
    send(server, {"jsonrpc": "2.0", "id": 5, "method": "resources/read",
                  "params": {"uri": "sales://schema"}})
finally:
    server.stdin.close()
    server.terminate()
