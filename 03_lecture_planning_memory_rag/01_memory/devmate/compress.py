"""Стиснення контексту, коли діалог перестає вміщатися у вікно моделі.

Історія ділиться на три частини:

    [голова]  постановка задачі — не чіпаємо ніколи
    [середина] ────► один підсумок від моделі
    [хвіст]   останні ходи — потрібні дослівно

Стискається лише середина. Голова задає, навіщо все почалося, хвіст —
що відбувається просто зараз; втратити будь-що з них найдорожче.

Важливо: стиснення не втрачає даних назавжди. Повний текст лишається
в архіві сесій, і `session_search` знайде його й після стиснення.
"""

from . import llm, memory

# Стискаємо, коли промпт перевищив цю межу. У Hermes поріг рахується від
# вікна моделі; тут задано числом, щоб на лекції легко було занизити.
THRESHOLD_TOKENS = 6000

# Скільки перших повідомлень захищено від стиснення.
PROTECT_FIRST = 2

# Яку частку порогу лишаємо хвосту.
TAIL_RATIO = 0.3

PROMPT = """\
Стисни фрагмент робочого діалогу асистента розробника в конспект.
Це не переказ для людини, а робоча пам'ять: за конспектом асистент
має продовжити роботу так, ніби пам'ятає все сам.

Заповни розділи, порожні — пропусти:

## Задача
## Що вже зроблено
## Поточний стан
## Ухвалені рішення
## Важливі файли й команди
## Що лишилось

Пиши стисло, фактами. Зберігай точні імена файлів, команди, числа й шляхи:
саме їх асистент не зможе відновити.

{memory_context}
--- ФРАГМЕНТ ДІАЛОГУ ---
{transcript}
"""


def should_compress() -> bool:
    """Дивимось на реальний розмір останнього промпту, а не на оцінку."""
    history = llm.usage.prompt_history
    return bool(history) and history[-1] > THRESHOLD_TOKENS


def _user_boundaries(history: list[dict]) -> list[int]:
    """Індекси повідомлень користувача.

    Різати можна лише по них: якщо розрізати між викликом інструмента і
    його результатом, API поскаржиться на незакритий tool_call.
    """
    return [i for i, m in enumerate(history) if m["role"] == "user"]


def _render(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        if m["role"] == "tool":
            lines.append(f"[результат інструмента] {m['content'][:400]}")
        elif m.get("tool_calls"):
            names = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            lines.append(f"[виклик інструментів] {names}")
        elif m["content"]:
            lines.append(f"{m['role']}: {m['content']}")
    return "\n".join(lines)


def compress(history: list[dict]) -> list[dict]:
    """Замінює середину історії одним підсумком."""
    boundaries = _user_boundaries(history)
    if len(boundaries) < 3:
        return history  # ще нема чого стискати

    head_end = boundaries[min(PROTECT_FIRST, len(boundaries) - 2)]
    tail_start = _pick_tail(history, boundaries)
    if tail_start <= head_end:
        return history

    middle = history[head_end:tail_start]
    summary = _summarize(_render(middle))

    return [
        *history[:head_end],
        {"role": "user", "content": f"[КОНСПЕКТ ПОПЕРЕДНЬОЇ РОЗМОВИ]\n{summary}"},
        *history[tail_start:],
    ]


def _pick_tail(history: list[dict], boundaries: list[int]) -> int:
    """Найдовший хвіст, що вміщається у виділений бюджет."""
    budget = THRESHOLD_TOKENS * TAIL_RATIO
    for start in boundaries:
        # Приблизна оцінка: 3 символи на токен. Точність тут не критична —
        # це вибір межі, а не облік витрат.
        size = sum(len(str(m.get("content", ""))) for m in history[start:]) / 3
        if size <= budget:
            return start
    return boundaries[-1]


def _summarize(transcript: str) -> str:
    """Конспект робить сама модель — інакше не відрізнити важливе від шуму."""
    context = memory.render_all()
    block = (
        f"--- ЩО АСИСТЕНТ УЖЕ ЗНАЄ (не дублюй це в конспекті) ---\n{context}\n"
        if context
        else ""
    )
    message = llm.chat(
        [
            {
                "role": "user",
                "content": PROMPT.format(memory_context=block, transcript=transcript),
            }
        ]
    )
    return message.content or "(конспект не вдався)"
