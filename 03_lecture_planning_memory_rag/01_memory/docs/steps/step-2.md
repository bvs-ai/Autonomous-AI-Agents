# Крок 2 — довготривала пам'ять

Два файли, `memories/MEMORY.md` і `memories/USER.md`, які переживають
перезапуск. Агент керує ними сам.

## Запис — це просто рядок

Ніяких таймстемпів, тегів, джерел, ембедингів. Записи в файлі розділені
`\n§\n`:

```python
DELIMITER = "\n§\n"

STORES = {
    "memory": ("MEMORY.md", "MEMORY (твої нотатки)", 2200),
    "user":   ("USER.md",   "USER PROFILE (хто такий користувач)", 1375),
}
```

Третє число — ліміт **у символах**, не в токенах. Символи однакові для
будь-якої моделі й токенізатора, тому їх можна зашити в код.

## Читання з диска

```python
def _read(self) -> list[str]:
    if not self.path.exists():
        return []
    raw = self.path.read_text(encoding="utf-8").split(DELIMITER)
    return list(dict.fromkeys(e.strip() for e in raw if e.strip()))
```

`dict.fromkeys` — дедуплікація, що зберігає порядок і лишає перший
екземпляр. Однорядковий замінник `set`, який порядок би зруйнував.

## Запис на диск — атомарний

```python
def _write(self) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = self.path.with_suffix(".tmp")
    tmp.write_text(DELIMITER.join(self.entries), encoding="utf-8")
    tmp.replace(self.path)
```

Пишемо в тимчасовий файл і перейменовуємо. `rename` атомарний, тому падіння
посеред запису не лишить обрізаної пам'яті.

## Як пам'ять потрапляє в промпт

```python
def render(self) -> str:
    if not self.entries:
        return ""
    used = self.size(self.entries)
    line = "═" * 46
    percent = round(100 * used / self.limit)
    return (
        f"{line}\n{self.header} [{percent}% — {used}/{self.limit} символів]\n"
        f"{line}\n" + DELIMITER.join(self.entries)
    )
```

Результат виглядає так:

```
══════════════════════════════════════════════
USER PROFILE (хто такий користувач) [5% — 64/1375 символів]
══════════════════════════════════════════════
Борис — викладач автономних агентних систем. Відповідати стисло.
```

Відсоток заповнення видно **моделі**. Це не декорація: у кроці 3 саме він
змусить її консолідувати записи заздалегідь.

## Заморожений знімок — головне рішення кроку

`agent.py`:

```python
def __init__(self, on_tool=None):
    # Знімок пам'яті береться один раз і до кінця сесії не змінюється:
    # prefix cache живе, лише поки початок промпту побайтово той самий.
    self.memory_snapshot = memory.render_all()

def system_prompt(self) -> str:
    if not self.memory_snapshot:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n{self.memory_snapshot}\n"
```

Пам'ять збирається **один раз**, у конструкторі. Якби вона перезбиралася на
кожній ітерації, кожен новий запис змінював би початок промпту — і prefix
cache скидався б повністю на кожному ході.

Наслідок: записане зараз потрапить у промпт лише наступного запуску. На диск
воно лягає негайно, і відповідь інструмента показує актуальний стан, тому
агент не плутається.

## Інструмент без операції читання

```python
def memory(target: str, operations: list | None = None, **single) -> str:
    # Дії `read` немає навмисно: пам'ять уже в системному промпті.
    return memory_store.apply(target, operations or [single])
```

Є лише `add`, `replace`, `remove`. Читати нічого — вміст уже перед очима
моделі. Це прибирає цілий клас зайвих викликів.

## Пошук за підрядком

Щоб змінити запис, моделі не треба відтворювати його дослівно:

```python
def _find(entries: list[str], fragment: str) -> int:
    fragment = fragment.strip()
    hits = [i for i, e in enumerate(entries) if fragment in e]
    if not hits:
        raise ValueError(f"жоден запис не містить '{fragment}'")
    if len(hits) > 1:
        raise ValueError(
            f"'{fragment}' збігається з {len(hits)} записами — вкажіть довший фрагмент"
        )
    return hits[0]
```

Кілька збігів — відмова. Інакше агент мовчки зіпсував би не той запис.

## Опис інструмента — це промпт

Найдовший рядок у `tools.py` — не код, а текст для моделі: коли зберігати
(«щойно користувач висловив уподобання чи виправив тебе»), який пріоритет
(«уподобання й виправлення > факти про оточення > процедури») і що **не**
зберігати («очевидне, сирі дані, прогрес по задачі»).

Без цих підказок модель або мовчить, або засмічує пам'ять дрібницями.

## Перевірити

```
› Я Борис, викладаю агентні системи. Відповідай стисло.
  [memory] add target=user → Додано.
› /memory        # на диску є, у знімку промпту ще немає
› /quit
› .venv/bin/python -m devmate.cli
› Як мене звати?
```
