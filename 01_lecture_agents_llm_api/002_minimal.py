"""Один запит до LLM на голому requests — без SDK.

Виклик LLM = звичайний HTTP POST на /chat/completions. Далі все лише нарощується.

"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

response = requests.post(
    f"{os.environ['OPENAI_BASE_URL']}/chat/completions",
    headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    json={
        "model": os.environ["LLM_MODEL"],
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": "Назви столицю Австралії та поточний рік. Відповідай одним рядком.",
            }
        ],
    },
)

body = response.json()

print(body["choices"][0]["message"]["content"])
