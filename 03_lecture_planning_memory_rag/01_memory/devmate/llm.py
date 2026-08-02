"""Виклик моделі.

Hermes ходить у LLM напряму через `openai`, без фреймворків — робимо так само.

Окремо рахуємо токени: на лекції це головний вимірювальний прилад. Саме
зростання `prompt_tokens` пояснює, навіщо пам'яті потрібен ліміт.
"""

from openai import OpenAI

from . import config

_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


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


def chat(messages: list[dict], tools: list[dict] | None = None):
    """Один виклик моделі. Повертає message з відповіді."""
    response = _client.chat.completions.create(
        model=config.MODEL,
        messages=messages,
        tools=tools or None,
    )
    usage.add(response.usage)
    return response.choices[0].message
