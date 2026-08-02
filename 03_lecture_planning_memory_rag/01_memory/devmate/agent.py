"""Цикл агента: модель → інструменти → модель → відповідь.

Агент має довготривалу пам'ять: вона підмішується в системний промпт
знімком, зафіксованим на старті сесії (див. `memory_snapshot`).
"""

import json

from . import compress, llm, memory, sessions, tools
from .config import MAX_ITERATIONS, WORKSPACE

SYSTEM_PROMPT = f"""\
Ти — DevMate, асистент розробника в терміналі. Робочий каталог: {WORKSPACE}

- Питання про код — спершу подивись інструментами, не вгадуй.
- Не про код — просто відповідай, інструменти не потрібні.
- Помітив стійкий факт про користувача чи проєкт — одразу збережи через memory.
- Відповідай стисло, конкретно, українською.
"""


class Agent:
    def __init__(self, on_tool=None, on_compress=None):
        # Колбеки — щоб CLI показував користувачу виклики і стиснення.
        self.on_tool = on_tool
        self.on_compress = on_compress
        self.history: list[dict] = []

        # Знімок пам'яті береться один раз і до кінця сесії не змінюється:
        # prefix cache живе, лише поки початок промпту побайтово той самий.
        # Тому записане зараз потрапить у промпт лише наступного запуску.
        self.memory_snapshot = memory.render_all()

        # Кожна сесія пишеться в state.db цілком і назавжди. На відміну від
        # MEMORY.md, тут немає ні ліміту, ні курування — тільки архів.
        self.session_id = sessions.new_session_id()

    def system_prompt(self) -> str:
        if not self.memory_snapshot:
            return SYSTEM_PROMPT
        return f"{SYSTEM_PROMPT}\n{self.memory_snapshot}\n"

    def run_turn(self, user_input: str) -> str:
        memory.start_turn()
        self.history.append({"role": "user", "content": user_input})
        sessions.save(self.session_id, "user", user_input)

        for _ in range(MAX_ITERATIONS):
            messages = [{"role": "system", "content": self.system_prompt()}, *self.history]
            message = llm.chat(messages, tools.SCHEMAS)

            if not message.tool_calls:
                answer = message.content or "(порожня відповідь)"
                self.history.append({"role": "assistant", "content": answer})
                sessions.save(self.session_id, "assistant", answer)
                self._maybe_compress()
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


    def _maybe_compress(self) -> None:
        """Стискаємо на межі ходу, а не посеред нього.

        Усередині ходу історія містить незакриті пари виклик-результат,
        різати її там небезпечно.
        """
        if not compress.should_compress():
            return
        before = len(self.history)
        self.history = compress.compress(self.history)
        if self.on_compress and len(self.history) < before:
            self.on_compress(before, len(self.history))


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
