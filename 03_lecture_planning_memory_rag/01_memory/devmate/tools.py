"""Інструменти агента.

Реєстрація — через декоратор `@tool`: поруч із функцією одразу видно
її JSON-схему. У наступних кроках демо сюди тим самим декоратором
додадуться `memory` і `session_search`.
"""

import subprocess
from pathlib import Path

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
