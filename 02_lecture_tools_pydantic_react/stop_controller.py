"""StopController -- єдиний інтерфейс стоп-критеріїв ReAct-циклу.

Єдиний модуль без номера в цій серії: його використовують одразу дві демо --
017 (перевірка критеріїв без LLM) і 018 (той самий контролер усередині графа).
Це й ілюструє суть: стоп-критерії -- окремий компонент, а не пара if'ів,
розкиданих по вузлах графа.

Чому один критерій не рятує:
  max_steps    -- ловить нескінченний цикл, але не ловить 5 кроків по 200k токенів;
  max_tokens   -- ловить спалений бюджет, але не ловить зависання на повільному API;
  timeout      -- ловить зависання, але не ловить швидке тупцювання на місці;
  loop detection -- ловить «продуктивне на вигляд» повторення того самого виклику.
"""

import time


class StopController:
    def __init__(
        self,
        max_steps: int = 6,
        max_tokens: int = 50_000,
        timeout: float = 60.0,
        max_repeats: int = 3,
    ):
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_repeats = max_repeats
        self.reset()

    def reset(self) -> None:
        """Контролер зберігає стан прогону -- перед новим запуском його треба скинути."""
        self.start_time = time.time()
        self.history: list[str] = []

    def should_stop(self, step: int, tokens: int, tool_calls: list[str]) -> tuple[bool, str]:
        """Повертає (стоп?, причина). Причина -- це те, що побачить користувач
        замість відповіді, тому вона має бути зрозумілою людині."""
        if step >= self.max_steps:
            return True, f"Досягнуто ліміт кроків ({self.max_steps})"

        if tokens > self.max_tokens:
            return True, f"Вичерпано бюджет токенів ({tokens} > {self.max_tokens})"

        if time.time() - self.start_time > self.timeout:
            return True, f"Таймаут ({self.timeout}s)"

        self.history.extend(tool_calls)
        recent = self.history[-self.max_repeats:]
        if len(recent) == self.max_repeats and len(set(recent)) == 1:
            return True, f"Зациклювання: {self.max_repeats} рази поспіль {recent[0]}"

        return False, ""
