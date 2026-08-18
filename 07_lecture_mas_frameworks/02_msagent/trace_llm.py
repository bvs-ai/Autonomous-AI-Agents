"""Найпростіший трейс для MAF: що пішло в модель і що вона відповіла.

Той самий інструмент, що й `01_crewai/trace_llm.py`, тільки замість шини подій
CrewAI тут штатна точка входу MAF — chat middleware. Друкує по блоку на КОЖЕН
виклик LLM: системну інструкцію, усі повідомлення запиту, доступні тули
й відповідь моделі (текст або виклик інструмента) з токенами.

Важливо, чого не видно в `context.messages`: інструкція агента їде окремим
полем `options["instructions"]`, а не повідомленням. Тому друкуємо її окремо —
інакше на екрані буде не весь оплачений контекст.

Вмикається одним рядком у будь-якому кроці:

    import trace_llm; trace_llm.on()

Запит друкується повністю щоразу, і це не марнотратство виводу, а суть:
у моделі немає сесії, тож на кожному виклику історія летить наново
і оплачується наново. Повторення на екрані — це і є те, за що заплачено.

Якщо на екрані задовго: trace_llm.on(limit=300).
"""
from contextvars import ContextVar

from agent_framework import AgentContext, ChatContext

ENABLED = False
LIMIT: int | None = None  # None — друкувати повністю; число — обрізати


def on(limit: int | None = None) -> None:
    """Вмикає трейс. Викликати до запуску воркфлоу."""
    global ENABLED, LIMIT
    ENABLED, LIMIT = True, limit


def _fmt(text: object) -> str:
    """Тіло повідомлення друкується з початку рядка, без відступів."""
    s = str(text)
    if LIMIT is not None and len(s) > LIMIT:
        return " ".join(s.split())[:LIMIT] + " […]"
    return s


def _contents(message) -> list[str]:
    """Розкладає повідомлення на людські рядки: текст, виклики тулів, їх результати."""
    out: list[str] = []
    for c in getattr(message, "contents", []) or []:
        # У MAF один клас Content на всі види, вид лежить у полі .type
        kind = getattr(c, "type", None)
        if kind == "function_call":
            out.append(f"    ⚙ виклик {c.name}({_fmt(c.arguments)})")
        elif kind == "function_result":
            out.append(f"    ↩ результат {_fmt(c.result)}")
        elif getattr(c, "text", None):
            out.append(_fmt(c.text))
        elif kind == "text_reasoning":
            # Gemini повертає міркування зашифрованими — тексту тут немає,
            # але токени за них порахують. Показуємо сам факт.
            out.append("    (міркування моделі, тіло приховане провайдером)")
        else:
            out.append(f"    ({kind})")
    return out


_n = 0  # наскрізний номер виклику LLM за весь прогін

# Ім'я агента, що зараз працює. У ChatContext його немає: клієнт один на всіх,
# і на рівні виклику моделі видно лише повідомлення й опції. Тому знімаємо ім'я
# поверхом вище — в agent middleware — і кладемо в ContextVar, щоб не плутати
# паралельні запуски.
_current_agent: ContextVar[str] = ContextVar("current_agent", default="?")


async def whoami(context: AgentContext, call_next) -> None:
    """Agent middleware: запам'ятовує, чий зараз хід.

    Додається до агента так:  client.as_agent(..., middleware=[trace_llm.whoami])
    """
    token = _current_agent.set(getattr(context.agent, "name", None) or "?")
    try:
        await call_next()
    finally:
        _current_agent.reset(token)


async def trace(context: ChatContext, call_next) -> None:
    """Chat middleware: друкує запит до моделі й відповідь на нього."""
    if not ENABLED:
        await call_next()
        return

    global _n
    _n += 1
    options = context.options or {}

    print(f"\n{'━' * 70}\n[{_n}] ▸ {_current_agent.get()}")

    if instructions := options.get("instructions"):
        print("--- IN instructions (окреме поле, не повідомлення):")
        print(_fmt(instructions))

    for m in context.messages:
        # Друкуємо і роль, і автора: роль каже, ЯК повідомлення бачить модель
        # (user / assistant / tool), автор — хто з агентів його породив.
        role = str(m.role)
        author = getattr(m, "author_name", None)
        who = f"{role} · {author}" if author else role
        print(f"--- IN {who}:")
        for line in _contents(m) or ["(порожньо)"]:
            print(line)

    if tools := options.get("tools"):
        names = [getattr(t, "name", None) or getattr(t, "__name__", "?") for t in tools]
        print(f"--- IN tools: {', '.join(names)}")

    await call_next()

    print("--- OUT:")
    for m in getattr(context.result, "messages", []) or []:
        for line in _contents(m):
            print(line)

    usage = getattr(context.result, "usage_details", None)
    if usage:
        print(
            f"--- токени: prompt={usage.get('input_token_count', 0)} "
            f"completion={usage.get('output_token_count', 0)}"
        )
