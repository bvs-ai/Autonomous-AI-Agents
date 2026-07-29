"""Перший агент: tool calling на голому requests.

Тут видно всю механіку без цукру — рукописна JSON Schema в TOOLS, цикл while,
ручне складання відповіді інструмента з tool_call_id. Модель нічого не виконує:
вона лише повертає намір, а викликає функцію наш код.

"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

ORDERS = [
    {"id": "A-1001", "status": "повернення", "days_since_delivery": 3},
    {"id": "A-1002", "status": "повернення", "days_since_delivery": 45},
    {"id": "A-1003", "status": "доставлено", "days_since_delivery": 1},
    {"id": "A-1004", "status": "повернення", "days_since_delivery": 12},
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Отримати список замовлень із заданим статусом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Статус українською: 'повернення' або 'доставлено'",
                    }
                },
                "required": ["status"],
            },
        },
    }
]

messages = [{"role": "user", "content": "Які замовлення зараз на поверненні? Перелічи їхні id."}]

while True:
#    print(f"[LLM_REQUEST_HISTORY] {json.dumps(messages, ensure_ascii=False, indent=2)}\n\n")
    response = requests.post(
        f"{os.environ['OPENAI_BASE_URL']}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": os.environ["LLM_MODEL"],
            "stream": False,
            "messages": messages,
            "tools": TOOLS,
        },
    )
    body = response.json()
#    print(f"\n[RAW] {json.dumps(body, ensure_ascii=False, indent=2)}\n")

    message = body["choices"][0]["message"]
    print(f"[LLM_ANSWER] {json.dumps(message, ensure_ascii=False, indent=2)}\n\n")

    messages.append(message)

    if not message.get("tool_calls"):
        print(f"[FINAL_ANSWER] {message["content"]}\n")
        break

    for call in message["tool_calls"]:
        args = json.loads(call["function"]["arguments"])
        print(f"[TOOL_CALL] query_orders({args})\n")
        result = [o for o in ORDERS if o["status"] == args["status"]]
        print(f"[TOOL_CALL_RESULT] {result}\n")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
