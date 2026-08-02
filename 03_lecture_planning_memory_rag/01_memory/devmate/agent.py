"""Цикл агента: модель → інструменти → модель → відповідь.

Це ядро, на яке в наступних кроках накладатиметься пам'ять. Поки що агент
не пам'ятає нічого поза межами процесу: перезапустили — і все втрачено.
"""

import json

from . import llm, tools
from .config import MAX_ITERATIONS, WORKSPACE

SYSTEM_PROMPT = f"""\
Ти — DevMate, асистент розробника в терміналі. Робочий каталог: {WORKSPACE}

- Не вгадуй вміст проєкту: спершу подивись інструментами, потім відповідай.
- Відповідай стисло, конкретно, українською.
"""


class Agent:
    def __init__(self, on_tool=None):
        # on_tool(name, args, result) — щоб CLI показував виклики користувачу.
        self.on_tool = on_tool
        self.history: list[dict] = []

    def system_prompt(self) -> str:
        """Поки що статичний. У кроці 2 сюди додасться блок пам'яті."""
        return SYSTEM_PROMPT

    def run_turn(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})

        for _ in range(MAX_ITERATIONS):
            messages = [{"role": "system", "content": self.system_prompt()}, *self.history]
            message = llm.chat(messages, tools.SCHEMAS)

            if not message.tool_calls:
                answer = message.content or "(порожня відповідь)"
                self.history.append({"role": "assistant", "content": answer})
                return answer

            self.history.append(_assistant_message(message))

            # Модель може попросити кілька інструментів одразу — виконуємо всі,
            # інакше API поскаржиться на незакритий tool_call.
            for c in message.tool_calls:
                args = _parse_args(c.function.arguments)
                result = tools.call(c.function.name, args)
                if self.on_tool:
                    self.on_tool(c.function.name, args, result)
                self.history.append(
                    {"role": "tool", "tool_call_id": c.id, "content": result}
                )

        return "Вичерпано ліміт викликів інструментів. Сформулюйте задачу вужче."


def _assistant_message(message) -> dict:
    # У reasoning-моделей `content` на ході з tool_calls порожній — це нормально.
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.function.name, "arguments": c.function.arguments},
            }
            for c in message.tool_calls
        ],
    }


def _parse_args(raw: str | None) -> dict:
    """Аргументи приходять рядком JSON і цілком можуть бути битими."""
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}
