"""Той самий діалог, що в 004, але через openai SDK.

Список messages лишається нашою відповідальністю — SDK його не веде.

"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

messages = []

while True:
    user_input = input("\n> ")
    if not user_input.strip():
        break

    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        stream=False,
        messages=messages,
    )
    message = response.choices[0].message
    messages.append(message)

    print(f"\n{message.content}")
