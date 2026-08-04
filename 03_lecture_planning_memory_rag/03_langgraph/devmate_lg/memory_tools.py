"""Памʼять: те, що в `../01_memory/devmate/memory.py` займало 287 рядків.

Store забирає зберігання, namespace і пошук. Не забирає **політику**: гейт
`scan()` і підтвердження людиною — це кроки 6 і 7 DevMate, і вони тут дослівно
такі самі, лише коротші.

Шлях запису рівно один — інструмент `remember`. Автоконсолідації (`post_model_hook`)
свідомо немає: два шляхи запису означали б два гейти й два місця для налагодження,
див. README.
"""
from langchain_core.tools import tool
from langgraph.config import get_store
from langgraph.runtime import get_runtime
from langgraph.types import interrupt

from .config import USER_ID
from .safety import scan


def current_user() -> str:
    """`user_id` береться з `context_schema`, а не зі стану (`04:792`).

    Поза графом (REPL читає памʼять напряму) рантайму немає — тоді дефолт.
    """
    try:
        return get_runtime().context.user_id
    except Exception:
        return USER_ID


def facts_ns(user_id: str | None = None) -> tuple[str, ...]:
    """Ізоляція тенантів адресою запису, а не фільтром (`04:1683`, OWASP LLM08)."""
    return ("users", user_id or current_user(), "facts")


# Факти, з якими агент стартує. У DevMate це вміст `memories/*.md`; тут вони
# засіваються при старті, бо InMemoryStore живе рівно стільки, скільки процес.
SEED_FACTS = {
    "tests": "Тести проєкту запускаються командою pytest -q.",
    "runner": "Старий раннер на unittest більше не підтримується — ним тести не запускати.",
    "timezones": "Планувальник звітів рахує дедлайни з таймзонами користувача.",
    "role": "Борис — викладач агентних систем (AI agents).",
    "style": "Борис любить стислі відповіді без води.",
}


def seed(store, user_id: str = USER_ID) -> None:
    for key, text in SEED_FACTS.items():
        store.put(facts_ns(user_id), key, {"text": text})


@tool
def remember(fact: str) -> str:
    """Зберегти стійкий факт про користувача або проєкт. Памʼять підставляється
    в кожну майбутню сесію, тому запис має бути коротким і незмінним у часі.
    Не зберігай нічого разового ("зараз відкрий файл") і нічого чутливого."""
    # Гейт №1 — політика: отруєний текст не має дійти навіть до питання людині.
    why = scan(fact)
    if why:
        return f"ЗАБЛОКОВАНО ({why}). Запис у памʼять не зроблено."
    # Дублікат не варто нести людині на підтвердження: памʼять живе роками, і
    # засмічують її саме повтори одного факта різними словами.
    if any(fact.strip().lower() == i.value["text"].strip().lower()
           for i in get_store().search(facts_ns())):
        return "Такий факт уже в памʼяті."
    # Гейт №2 — людина. `interrupt()` фізично неможливий без чекпоінтера: граф
    # стає, стан лягає в чекпоінт, процес може вмерти, `Command(resume=...)`
    # продовжує. Це найкраще пояснення, навіщо потрібен чекпоінтер.
    if not interrupt({"action": "remember", "fact": fact}):
        return "Людина відхилила запис."
    get_store().put(facts_ns(), fact[:40], {"text": fact})
    return f"Записано в памʼять: {fact}"


@tool
def forget(fragment: str) -> str:
    """Видалити з памʼяті записи, що містять цей фрагмент тексту."""
    store = get_store()
    gone = [i.key for i in store.search(facts_ns()) if fragment.lower() in i.value["text"].lower()]
    for key in gone:
        store.delete(facts_ns(), key)
    return f"Видалено записів: {len(gone)}" if gone else "Нічого не знайшлося."


def facts(store, query: str = "", limit: int = 20) -> list[tuple[float | None, str]]:
    """Читання памʼяті для REPL. З `query` — семантика, без нього — просто список.

    Саме тут ховається розвʼязка кроку 4: повнотекстовий `/search` не знаходив
    «таймзони», бо в записі стояло «таймзонами». Store проіндексований
    ембедингами — та сама поразка більше не відтворюється.
    """
    items = store.search(facts_ns(), query=query or None, limit=limit)
    return [(i.score, i.value["text"]) for i in items]
