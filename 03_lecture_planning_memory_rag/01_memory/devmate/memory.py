"""Довготривала пам'ять: MEMORY.md і USER.md.

Запис — просто рядок без таймстемпів і тегів. Записи розділені `\\n§\\n`.
Ліміт рахується в символах, а не в токенах: символи не залежать від моделі.

Читати пам'ять окремою дією не треба — вона вже в системному промпті.

Ліміт не стискає пам'ять сам. Переповнення — це відмова з переліком наявних
записів: що саме викинути, вирішує модель, бо тільки вона знає сенс записів.
"""

from .config import ROOT

DELIMITER = "\n§\n"
MEMORY_DIR = ROOT / "memories"

# Ліміти в символах: ~800 і ~500 токенів.
STORES = {
    "memory": ("MEMORY.md", "MEMORY (твої нотатки)", 2200),
    "user": ("USER.md", "USER PROFILE (хто такий користувач)", 1375),
}

# Скільки разів поспіль модель може провалити консолідацію за один хід.
MAX_FAILURES = 3
_failures = 0


class Store:
    """Один файл пам'яті — список рядків-записів."""

    def __init__(self, target: str):
        self.filename, self.header, self.limit = STORES[target]
        self.path = MEMORY_DIR / self.filename
        self.entries = self._read()

    def _read(self) -> list[str]:
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8").split(DELIMITER)
        # dict.fromkeys прибирає дублікати, зберігаючи порядок.
        return list(dict.fromkeys(e.strip() for e in raw if e.strip()))

    def _write(self) -> None:
        # Атомарно: падіння посеред запису інакше лишить обрізаний файл.
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(DELIMITER.join(self.entries), encoding="utf-8")
        tmp.replace(self.path)

    def size(self, entries: list[str]) -> int:
        return len(DELIMITER.join(entries))

    def render(self) -> str:
        """Блок для системного промпту.

        Відсоток заповнення показується моделі навмисно: вона має бачити,
        що місце закінчується, і консолідувати записи заздалегідь.
        """
        if not self.entries:
            return ""
        used = self.size(self.entries)
        line = "═" * 46
        percent = round(100 * used / self.limit)
        return (
            f"{line}\n{self.header} [{percent}% — {used}/{self.limit} символів]\n"
            f"{line}\n" + DELIMITER.join(self.entries)
        )


stores = {name: Store(name) for name in STORES}


def render_all() -> str:
    """Знімок усієї пам'яті для системного промпту."""
    return "\n\n".join(b for b in (s.render() for s in stores.values()) if b)


def start_turn() -> None:
    """Скидає лічильник невдач на межі ходу."""
    global _failures
    _failures = 0


def _find(entries: list[str], fragment: str) -> int:
    """Знаходить запис за коротким унікальним фрагментом.

    Моделі не треба відтворювати запис дослівно. Але якщо фрагмент збігся
    з кількома записами — відмовляємо, інакше зіпсуємо не той запис.
    """
    fragment = fragment.strip()
    hits = [i for i, e in enumerate(entries) if fragment in e]
    if not hits:
        raise ValueError(f"жоден запис не містить '{fragment}'")
    if len(hits) > 1:
        raise ValueError(
            f"'{fragment}' збігається з {len(hits)} записами — вкажіть довший фрагмент"
        )
    return hits[0]


def _apply_one(entries: list[str], op: dict) -> str:
    """Виконує одну операцію над копією списку записів."""
    action = op.get("action")
    content = (op.get("content") or "").strip()
    old_text = op.get("old_text") or ""

    if action == "add":
        if content in entries:
            return "дублікат пропущено"
        entries.append(content)
        return "додано"
    if action == "replace":
        entries[_find(entries, old_text)] = content
        return "замінено"
    if action == "remove":
        entries.pop(_find(entries, old_text))
        return "видалено"
    raise ValueError(f"невідома дія '{action}'")


def apply(target: str, operations: list[dict]) -> str:
    """Виконує пакет операцій атомарно: або всі, або жодної.

    Ліміт перевіряється лише за фінальним станом. Тому один виклик може
    видалити застаріле і додати нове разом — навіть якщо саме лише
    додавання переповнило б пам'ять.
    """
    global _failures

    store = stores.get(target)
    if store is None:
        return f"ПОМИЛКА: невідоме сховище '{target}'. Доступні: memory, user."

    entries = list(store.entries)
    try:
        results = [_apply_one(entries, op) for op in operations]
    except ValueError as exc:
        return f"ПОМИЛКА: {exc}"

    used = store.size(entries)
    if used > store.limit:
        return _overflow(store, used)

    store.entries = entries
    store._write()
    _failures = 0
    return f"{', '.join(results)}. Зайнято {used}/{store.limit} символів."


def _overflow(store: Store, used: int) -> str:
    """Відмова з переліком записів — щоб модель знала, що консолідувати."""
    global _failures
    _failures += 1

    if _failures >= MAX_FAILURES:
        # Інакше модель зациклюється на пам'яті й не відповідає користувачу.
        return (
            "ПОМИЛКА: пам'ять переповнено, спроби консолідації вичерпано. "
            "Припиніть writes і відповідайте користувачу."
        )

    listing = "\n".join(f"  {i}. {e}" for i, e in enumerate(store.entries, 1))
    return (
        f"ПОМИЛКА: не вміщується — вийде {used}/{store.limit} символів.\n"
        f"Наявні записи:\n{listing}\n"
        "Повторіть ОДНИМ викликом з масивом operations: приберіть або "
        "скоротіть застаріле і додайте нове разом."
    )
