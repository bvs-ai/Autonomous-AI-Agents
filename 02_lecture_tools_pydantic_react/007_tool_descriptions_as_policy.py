"""Схема задає ГРАМАТИКУ виклику, description -- СЕМАНТИКУ: коли інструмент
застосовувати, а коли ні. Strict-режим (006) гарантує валідні аргументи, але
жодним чином не гарантує, що модель обере ПОТРІБНИЙ інструмент.

Два інструменти з ОДНАКОВОЮ схемою (обидва беруть order_id): повернення грошей
і гарантійний ремонт. Правильний вибір залежить від правила, якого модель не
може вгадати: вікно повернення -- 30 днів, далі лишається лише гарантія.

Головне тут -- не «подивіться, як модель помилилась», а те, що вибір інструмента
треба ВИМІРЮВАТИ. Нижче -- мінімальний eval: набір питань з відомою правильною
відповіддю проганяється двома наборами описів, рахується точність. Це той самий
«тест на стажера» з лекції, тільки автоматизований: якщо стажер за описом не
розуміє, що брати -- модель тим більше.

Строгий критерій: зараховуємо лише РІВНО потрібний інструмент. Зайві виклики
«про всяк випадок» -- теж помилка: це витрачені токени і зайві побічні ефекти.

Потребує заповненого .env. Робить 2 x len(CASES) викликів LLM.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()
MODEL = os.environ["LLM_MODEL"]

# Схеми ідентичні -- отже вибір інструмента визначає ВИКЛЮЧНО опис.
ORDER_ID_SCHEMA = {
    "type": "object",
    "properties": {"order_id": {"type": "string", "pattern": r"^A-\d{4}$"}},
    "required": ["order_id"],
    "additionalProperties": False,
}


def build_tools(descriptions: dict[str, str]) -> list[dict]:
    return [
        {"type": "function", "function": {"name": name, "description": text, "parameters": ORDER_ID_SCHEMA}}
        for name, text in descriptions.items()
    ]


# Описи «правдиві» і виглядають пристойно -- але не кажуть, ЧИМ інструменти
# відрізняються і за яким правилом обирати між ними.
VAGUE = build_tools(
    {
        "check_return_policy": "Оформлення повернення товару.",
        "check_warranty": "Перевірка гарантії на товар.",
    }
)

# Ті самі інструменти, але опис -- це вже політика вибору.
CLEAR = build_tools(
    {
        "check_return_policy": (
            "Перевірити можливість ПОВЕРНЕННЯ ГРОШЕЙ за замовленням. "
            "Вікно повернення -- 30 днів з дати доставки. "
            "НЕ використовувати, якщо з моменту доставки минуло понад 30 днів: "
            "у такому разі єдиний шлях -- check_warranty."
        ),
        "check_warranty": (
            "Перевірити гарантійне обслуговування (ремонт або заміна) для товару, що зламався. "
            "Гарантія діє 12 місяців і застосовується САМЕ ТОДІ, "
            "коли вікно повернення в 30 днів уже минуло."
        ),
    }
)

# Питання -> єдиний інструмент, який має бути викликаний.
CASES = {
    "Замовлення A-1001 доставили 3 дні тому, товар не підійшов. Що робити?": "check_return_policy",
    "Замовлення A-1002 доставили 40 днів тому, товар зламався. Що робити?": "check_warranty",
    "Замовлення A-1003 доставили пів року тому, перестало вмикатися. Що робити?": "check_warranty",
    "Замовлення A-1004 прийшло вчора, колір не той. Хочу гроші назад.": "check_return_policy",
}


def chosen_tools(tools: list[dict], question: str) -> list[str]:
    """Один виклик LLM: цікавить лише те, які інструменти модель узяла в роботу."""
    response = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": question}], tools=tools, temperature=0
    )
    return [call.function.name for call in response.choices[0].message.tool_calls or []]


def evaluate(label: str, tools: list[dict]) -> None:
    hits = 0
    hedged = 0
    print(f"[{label}]")
    for question, expected in CASES.items():
        picked = chosen_tools(tools, question)
        hits += picked == [expected]
        hedged += len(picked) > 1
        print(f"    {'OK  ' if picked == [expected] else 'MISS'} очікували [{expected}], отримали {picked}")
    print(f"    точність: {hits}/{len(CASES)}   hedging (>1 виклику): {hedged}/{len(CASES)}\n")


if __name__ == "__main__":
    for label, tools in [("VAGUE", VAGUE), ("CLEAR", CLEAR)]:
        evaluate(label, tools)

    print(
        "Схеми обох інструментів однакові й не змінювались -- змінювався лише текст description.\n"
        "Якщо в MISS видно ОБИДВА інструменти -- це hedging: модель викликає все підряд,\n"
        "бо опис не дав їй критерію вибору. Ціна -- зайві токени і зайві побічні ефекти.\n"
        "І навпаки: навіть найкращий опис лише ЗСУВАЄ ймовірність, а не гарантує вибір --\n"
        "гарантії дає рантайм: strict-схема (006) і allowlist на виконанні (013)."
    )
