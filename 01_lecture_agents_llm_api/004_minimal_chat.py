"""Діалог у циклі на requests: «пам'ять» — це просто список messages.

На боці моделі стану немає: всю історію ми щоразу надсилаємо повністю заново.

"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

messages = []

while True:
    user_input = input("\n> ")
    if not user_input.strip():
        break

    messages.append({"role": "user", "content": user_input})

    response = requests.post(
        f"{os.environ['OPENAI_BASE_URL']}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": os.environ["LLM_MODEL"],
            "stream": False,
            "messages": messages,
        },
    )
    message = response.json()["choices"][0]["message"]
    messages.append(message)

    print(f"\n{message['content']}")
