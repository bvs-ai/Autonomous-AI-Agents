"""Довготривала пам'ять: MEMORY.md і USER.md.

Запис — просто рядок без таймстемпів і тегів. Записи розділені `\\n§\\n`.
Ліміт рахується в символах, а не в токенах: символи не залежать від моделі.

Читати пам'ять окремою дією не треба — вона вже в системному промпті.
"""

from pathlib import Path

from .config import ROOT

DELIMITER = "\n§\n"

MEMORY_DIR = ROOT / "memories"

# Ліміти з дефолтів Hermes: ~800 і ~500 токенів при 2.75 символа на токен.
STORES = {
    "memory": ("MEMORY.md", "MEMORY (твої нотатки)", 2200),
    "user": ("USER.md", "USER PROFILE (хто такий користувач)", 1375),
}


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
        """Атомарний запис: спершу у тимчасовий файл, потім rename.

        Інакше падіння посеред запису лишить обрізаний файл пам'яті.
        """
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(DELIMITER.join(self.entries), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def used(self) -> int:
        return len(DELIMITER.join(self.entries))

    def add(self, content: str) -> str:
        content = content.strip()
        if content in self.entries:
            return "Запис уже існує (дублікат не додано)."
        self.entries.append(content)
        self._write()
        return f"Додано. {self.usage()}"

    def replace(self, old_text: str, content: str) -> str:
        index = self._find(old_text)
        if isinstance(index, str):
            return index
        self.entries[index] = content.strip()
        self._write()
        return f"Замінено. {self.usage()}"

    def remove(self, old_text: str) -> str:
        index = self._find(old_text)
        if isinstance(index, str):
            return index
        self.entries.pop(index)
        self._write()
        return f"Видалено. {self.usage()}"

    def _find(self, old_text: str) -> int | str:
        """Пошук запису за короткою унікальною підрядкою.

        Моделі не треба відтворювати запис дослівно — достатньо фрагмента.
        Але якщо фрагмент збігся з кількома записами, це помилка: інакше
        агент мовчки зіпсує не той запис.
        """
        old_text = old_text.strip()
        hits = [i for i, e in enumerate(self.entries) if old_text in e]
        if not hits:
            return f"ПОМИЛКА: жоден запис не містить '{old_text}'."
        if len(hits) > 1:
            return (
                f"ПОМИЛКА: '{old_text}' збігається з {len(hits)} записами. "
                "Вкажіть довший фрагмент."
            )
        return hits[0]

    def usage(self) -> str:
        return f"Зайнято {self.used}/{self.limit} символів."

    def render(self) -> str:
        """Блок для системного промпту.

        Відсоток заповнення показується моделі навмисно: вона має бачити,
        що місце закінчується, і сама вирішувати консолідувати записи.
        """
        if not self.entries:
            return ""
        percent = round(100 * self.used / self.limit)
        line = "═" * 46
        return (
            f"{line}\n{self.header} [{percent}% — {self.used}/{self.limit} символів]\n"
            f"{line}\n" + DELIMITER.join(self.entries)
        )


stores = {name: Store(name) for name in STORES}


def render_all() -> str:
    """Знімок усієї пам'яті для системного промпту."""
    blocks = [s.render() for s in stores.values()]
    return "\n\n".join(b for b in blocks if b)


def apply(action: str, target: str, content: str = "", old_text: str = "") -> str:
    store = stores.get(target)
    if store is None:
        return f"ПОМИЛКА: невідоме сховище '{target}'. Доступні: memory, user."
    if action == "add":
        return store.add(content)
    if action == "replace":
        return store.replace(old_text, content)
    if action == "remove":
        return store.remove(old_text)
    return f"ПОМИЛКА: невідома дія '{action}'."
