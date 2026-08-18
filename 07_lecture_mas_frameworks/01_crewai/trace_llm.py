"""Найпростіший трейс: що пішло в модель і що вона відповіла.

Вмикається одним рядком у будь-якому кроці:

    import trace_llm; trace_llm.on()

Друкує по одному блоку на КОЖЕН виклик LLM, у реальному порядку: хто говорить
(виконавець або менеджер), увесь запит цілком і що модель відповіла — текст
або виклик інструмента.

Запит друкується повністю щоразу, і це не марнотратство виводу, а суть:
у моделі немає сесії, тож на кожному виклику історія летить у запит наново
і оплачується наново. Повторення на екрані — це і є те, за що заплачено.

Якщо на екрані задовго, є обрізка кожного повідомлення: trace_llm.on(limit=300).
"""
from crewai.events import BaseEventListener
from crewai.events.types.llm_events import (
    LLMCallCompletedEvent,
    LLMCallStartedEvent,
)

LIMIT: int | None = None  # None — друкувати повністю; число — обрізати


def _fmt(text: object) -> str:
    """Готує текст повідомлення до друку.

    Тіло повідомлення друкується з початку рядка, без відступів: промпти
    багаторядкові, і будь-яке вирівнювання по колонці лише плутає, де
    закінчується наш заголовок і починається текст, що пішов у модель.
    """
    s = str(text)
    if LIMIT is not None and len(s) > LIMIT:
        return " ".join(s.split())[:LIMIT] + " […]"
    return s


class _Trace(BaseEventListener):
    def __init__(self) -> None:
        self.n = 0  # наскрізний номер виклику LLM за весь прогін
        super().__init__()

    def setup_listeners(self, bus) -> None:
        @bus.on(LLMCallStartedEvent)
        def _started(source, event):
            self.n += 1
            who = getattr(event, "agent_role", None) or "менеджер"
            print(f"\n{'━' * 70}\n[{self.n}] ▸ {who}")

            for m in event.messages or []:
                role = m.get("role", "?") if isinstance(m, dict) else "?"
                body = m.get("content") if isinstance(m, dict) else m
                print(f"--- IN {role}:")
                print(_fmt(body))

        @bus.on(LLMCallCompletedEvent)
        def _completed(source, event):
            calls = _tool_calls(event.response)
            if calls:
                for name, args in calls:
                    print(f"--- OUT tool: {name}")
                    print(_fmt(args))
            else:
                print("--- OUT text:")
                print(_fmt(event.response))


def _tool_calls(response: object) -> list[tuple[str, object]]:
    """Витягує виклики інструментів із відповіді — формат залежить від провайдера."""
    parts = response if isinstance(response, list) else [response]
    out = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        fc = p.get("function_call") or p.get("function") or {}
        if isinstance(fc, dict) and fc.get("name"):
            out.append((fc["name"], fc.get("args") or fc.get("arguments")))
    return out


_listener = None


def on(limit: int | None = None) -> None:
    """Вмикає трейс. Викликати до kickoff().

    limit=None (за замовчуванням) — повні промпти й відповіді;
    limit=N — обрізати кожне повідомлення до N символів.
    """
    global _listener, LIMIT
    LIMIT = limit
    if _listener is None:
        _listener = _Trace()
