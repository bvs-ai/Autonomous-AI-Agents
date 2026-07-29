"""Той самий запит, що в 002, але через openai SDK.

SDK не робить нічого таємного — лише ховає HTTP: base_url і ключ бере з оточення,
тому OpenAI() без аргументів.

"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

response = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    stream=False,
    messages=[
        {
            "role": "user",
            "content": "Назви столицю Австралії та поточний рік. Відповідай одним рядком.",
        }
    ],
)

print(response.choices[0].message.content)
