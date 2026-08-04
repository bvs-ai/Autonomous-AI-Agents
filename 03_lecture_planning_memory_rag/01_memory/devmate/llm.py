"""Виклик моделі.

Hermes ходить у LLM напряму через `openai`, без фреймворків — робимо так само.

Окремо рахуємо токени: на лекції це головний вимірювальний прилад. Саме
зростання `prompt_tokens` пояснює, навіщо пам'яті потрібен ліміт.
"""

from openai import OpenAI
from rich.console import Console

from . import config

_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

# Прапорець живе тут, а не в config: CLI перемикає його на льоту через /context.
DEBUG_CONTEXT = config.DEBUG_CONTEXT

# Дамп іде в stderr, щоб не змішуватись із діалогом і щоб його можна було
# відвести у файл: `python -m devmate.cli 2> context.log`.
_debug_console = Console(stderr=True, soft_wrap=True)


class Usage:
    """Статистика викликів моделі за сесію."""

    def __init__(self):
        self.calls = 0
        self.prompt = 0
        self.completion = 0
        self.cached = 0
        self.prompt_history: list[int] = []

    def add(self, u) -> None:
        if not u:
            return
        self.calls += 1
        self.prompt += u.prompt_tokens
        self.completion += u.completion_tokens
        self.prompt_history.append(u.prompt_tokens)
        self.cached += _cached_tokens(u)

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    @property
    def cache_rate(self) -> float:
        return self.cached / self.prompt if self.prompt else 0.0


def _cached_tokens(u) -> int:
    """Про prefix cache провайдери повідомляють по-різному — читаємо обидва поля."""
    flat = getattr(u, "prompt_cache_hit_tokens", None)
    if flat is not None:
        return flat
    details = getattr(u, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0


usage = Usage()


def set_debug(on: bool) -> None:
    """Перемикач із CLI. Окрема функція, бо присвоєння з іншого модуля
    створило б там локальне імʼя замість зміни прапорця тут."""
    global DEBUG_CONTEXT
    DEBUG_CONTEXT = on


_ROLE_STYLE = {
    "system": "magenta",
    "user": "green",
    "assistant": "blue",
    "tool": "yellow",
}


def _clip(text: str) -> str:
    limit = config.DEBUG_CONTEXT_CHARS
    if limit and len(text) > limit:
        return text[:limit] + f"… [+{len(text) - limit} символів]"
    return text


def _dump(messages: list[dict], model: str) -> None:
    """Друкує рівно те, що піде в API.

    Саме тут видно те, чого не видно ніде більше: заморожений знімок пам'яті
    в system, пригаданий блок, підклеєний до повідомлення користувача, і
    результати інструментів як окремі повідомлення.
    """
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    _debug_console.rule(f"[bold]контекст → {model}[/] · {len(messages)} повідомлень · ~{chars:,} символів")

    for i, m in enumerate(messages):
        role = m.get("role", "?")
        style = _ROLE_STYLE.get(role, "white")
        head = f"[{style}][{i}] {role}[/]"

        # Виклики інструментів лежать не в content, а поруч — без них дамп
        # виглядав би так, ніби асистент відповів порожнечею.
        for call in m.get("tool_calls") or []:
            fn = call["function"]
            head += f" [dim]→ {fn['name']}({_clip(fn['arguments'])})[/]"
        if m.get("tool_call_id"):
            head += f" [dim]← {m['tool_call_id']}[/]"

        _debug_console.print(head)
        content = str(m.get("content") or "")
        if content:
            _debug_console.print(_clip(content), markup=False, highlight=False)

    _debug_console.rule()


def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None):
    """Один виклик моделі. Повертає message з відповіді.

    `model` потрібен ревʼю з кроку 6: воно може ходити в дешевшу модель.
    """
    if DEBUG_CONTEXT:
        _dump(messages, model or config.MODEL)
    response = _client.chat.completions.create(
        model=model or config.MODEL,
        messages=messages,
        tools=tools or None,
    )
    usage.add(response.usage)
    return response.choices[0].message
