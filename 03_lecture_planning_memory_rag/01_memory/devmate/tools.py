"""Інструменти агента.

Реєстрація — через декоратор `@tool`: поруч із функцією одразу видно
її JSON-схему. Опис інструмента — це частина промпту, тому він написаний
для моделі, а не для програміста.
"""

import subprocess
from pathlib import Path

from . import memory as memory_store
from . import sessions
from .config import WORKSPACE

# Ліміт на результат інструмента: один `cat` великого файлу інакше з'їсть вікно.
MAX_RESULT = 4000

HANDLERS = {}
SCHEMAS = []


def tool(description: str, params: dict, required: list[str] = []):
    """Реєструє функцію як інструмент, доступний моделі."""

    def register(fn):
        HANDLERS[fn.__name__] = fn
        SCHEMAS.append(
            {
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": params,
                        "required": required,
                    },
                },
            }
        )
        return fn

    return register


def call(name: str, args: dict) -> str:
    """Виконує інструмент. Помилка — не виняток, а текст для моделі.

    Модель повинна побачити, що саме пішло не так, і виправитись сама.
    Цей самий принцип у Hermes: інструмент повертає структуровану помилку
    замість того, щоб завалити хід.
    """
    if name not in HANDLERS:
        return f"ПОМИЛКА: інструмента '{name}' не існує."
    try:
        result = str(HANDLERS[name](**args))
    except Exception as exc:
        return f"ПОМИЛКА в '{name}': {exc}"
    if len(result) > MAX_RESULT:
        result = result[:MAX_RESULT] + "\n… [обрізано]"
    return result


def _path(raw: str) -> Path:
    """Не випускає агента за межі робочого каталогу (знімає і `../`, і симлінки)."""
    target = (WORKSPACE / raw).resolve()
    if not target.is_relative_to(WORKSPACE):
        raise ValueError(f"шлях '{raw}' поза робочим каталогом")
    return target


@tool("Показати вміст каталогу.", {"path": {"type": "string"}})
def list_dir(path: str = ".") -> str:
    items = sorted(p for p in _path(path).iterdir() if not p.name.startswith("."))
    return "\n".join(p.name + ("/" if p.is_dir() else "") for p in items) or "(порожньо)"


@tool(
    "Прочитати файл. Рядки повертаються пронумерованими.",
    {"path": {"type": "string"}},
    ["path"],
)
def read_file(path: str) -> str:
    text = _path(path).read_text(encoding="utf-8", errors="replace")
    return "\n".join(f"{i:4d}| {s}" for i, s in enumerate(text.splitlines(), 1))


@tool(
    "Знайти рядки за шаблоном у файлах проєкту.",
    {"pattern": {"type": "string"}, "path": {"type": "string"}},
    ["pattern"],
)
def grep(pattern: str, path: str = ".") -> str:
    out = subprocess.run(
        ["grep", "-rn", "--binary-files=without-match", pattern, str(_path(path))],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return out.stdout.strip() or "(збігів немає)"


@tool(
    "Виконати shell-команду в корені проєкту (тести, лінтер, git).",
    {"command": {"type": "string"}},
    ["command"],
)
def run_command(command: str) -> str:
    out = subprocess.run(
        command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=60
    )
    return f"exit={out.returncode}\n{out.stdout}{out.stderr}".strip()


# Опис інструмента — це теж промпт. Без підказок «коли зберігати» і «що НЕ
# зберігати» модель або мовчить, або засмічує пам'ять дрібницями.
@tool(
    "Зберегти стійкий факт у пам'ять, що переживе перезапуск. Пам'ять "
    "підставляється у кожну майбутню сесію, тому записи мають бути "
    "короткими й змістовними.\n\n"
    "ЯК: роби ВСІ зміни одним викликом через масив operations. Пакет "
    "застосовується цілком або ніяк, а ліміт перевіряється лише за "
    "результатом — тому один виклик може і прибрати застаріле, і додати "
    "нове. Одиночні поля action/content/old_text — лише для однієї зміни.\n\n"
    "КОЛИ: зберігай одразу, щойно користувач висловив уподобання чи "
    "виправив тебе, або ти дізнався стійкий факт про його оточення, "
    "домовленості чи робочий процес. Пріоритет: уподобання й виправлення "
    "> факти про оточення > процедури. Найкраща пам'ять — та, що позбавляє "
    "користувача потреби повторюватись.\n\n"
    "ЯКЩО ПОВНО: додавання буде відхилено з переліком наявних записів. "
    "Повтори ОДНИМ пакетом, що прибирає зайве і додає нове разом.\n\n"
    "СХОВИЩА: 'user' — хто такий користувач (ім'я, роль, уподобання, стиль). "
    "'memory' — твої нотатки (оточення, домовленості, особливості "
    "інструментів, засвоєні уроки).\n\n"
    "НЕ ЗБЕРІГАЙ: очевидне, те що легко з'ясувати наново, сирі дані, "
    "прогрес по задачі, тимчасовий стан.",
    {
        "target": {"type": "string", "enum": ["memory", "user"]},
        "action": {"type": "string", "enum": ["add", "replace", "remove"]},
        "content": {"type": "string", "description": "Текст запису для add/replace."},
        "old_text": {
            "type": "string",
            "description": "Короткий унікальний фрагмент наявного запису.",
        },
        "operations": {
            "type": "array",
            "description": "Кілька змін за раз; застосовуються атомарно.",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "content": {"type": "string"},
                    "old_text": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    ["target"],
)
def memory(target: str, operations: list | None = None, **single) -> str:
    # Дії `read` немає навмисно: пам'ять уже в системному промпті.
    # Одиночна зміна — це просто пакет з однієї операції.
    return memory_store.apply(target, operations or [single])


@tool(
    "Знайти, що обговорювалося в минулих сесіях. Пам'ять MEMORY.md коротка "
    "й містить лише головне; тут — повний архів усіх розмов. "
    "Використовуй, коли користувач посилається на щось раніше "
    "('як ми домовились', 'той баг', 'минулого разу') або коли потрібна "
    "деталь, якої немає в пам'яті. Пошук безкоштовний.",
    {
        "query": {"type": "string", "description": "Слова для пошуку."},
        "limit": {"type": "integer", "description": "Скільки збігів (типово 5)."},
    },
    ["query"],
)
def session_search(query: str, limit: int = 5) -> str:
    hits = sessions.search(query, limit)
    if not hits:
        return "Нічого не знайдено в минулих сесіях."
    return "\n".join(
        f"[{h['at']}] {h['role']}: {h['excerpt']}" for h in hits
    )
