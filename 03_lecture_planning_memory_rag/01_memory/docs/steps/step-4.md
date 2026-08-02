# Крок 4 — архів сесій

`MEMORY.md` — це те, що агент вирішив запам'ятати. `state.db` — усе, що
взагалі було сказано.

## Два сховища з протилежними властивостями

| | `MEMORY.md` | `state.db` |
|---|---|---|
| Обсяг | ~800 токенів | без обмежень |
| У промпті | завжди | тільки на запит |
| Хто наповнює | модель, вручну | пишеться саме |
| Ціна | токени в кожному запиті | ~0 |

Ключове: **пошук не коштує викликів моделі**. Жодних ембедингів, жодної
векторної бази — повнотекстовий індекс SQLite.

## Схема

```sql
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Далі — два індекси FTS5:

```sql
-- Пошук за словами. Швидкий і точний, але слово має збігтися повністю.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='unicode61'
);

-- Пошук за трилітерними фрагментами.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_trigram USING fts5(
    content, content='messages', content_rowid='id', tokenize='trigram'
);
```

`content='messages'` — це **зовнішній контент**: індекс не зберігає текст
удруге, а посилається на таблицю. Синхронність тримають тригери:

```sql
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
    INSERT INTO messages_trigram(rowid, content) VALUES (new.id, new.content);
END;
```

## Навіщо другий індекс

Це найкорисніший сюжет кроку, і він виявляється на очах.

Запишемо в одній сесії «баг із **таймзонами**», а в наступній спитаємо «що
там із **таймзонами**?». Словниковий індекс не знайде нічого: `unicode61`
не робить стемінгу, для нього це різні слова.

Тригамний індекс шукає підрядок, тому переживає словозміну. Але й тут є
пастка: «таймзони» **не є** підрядком «таймзонами» — розходяться закінчення.
Тому перед пошуком закінчення грубо відкидається:

```python
def _stem(word: str) -> str:
    word = word.strip(".,!?;:()[]\"'").lower()
    return word[:-2] if len(word) > 5 else word
```

Це не морфологія, але для пошуку по власному архіву вистачає й пояснюється
одним рядком.

## Стратегія пошуку

```python
def search(query: str, limit: int = 5) -> list[dict]:
    rows = _query_index("messages_fts", _fts_query(query), limit)

    seen = {r[0] for r in rows}
    for word in sorted(query.split(), key=len, reverse=True):
        if len(rows) >= limit:
            break
        stem = _stem(word)
        if len(stem) < 3:
            continue
        for row in _query_index("messages_trigram", stem, limit):
            if row[0] not in seen:
                seen.add(row[0])
                rows.append(row)
    return ...
```

Спершу точні збіги словами, потім добір тригамами. Точне цінніше, тому йде
першим; тригами дають ширше покриття, але й більше шуму.

Довші слова перебираються першими (`key=len, reverse=True`) — вони
специфічніші.

## Екранування запиту

У FTS5 своя мова запитів, де `-`, `*`, `"` мають особливий сенс. Запит
користувача треба знешкодити:

```python
def _fts_query(text: str) -> str:
    words = [w.replace('"', "") for w in text.split() if w.strip()]
    return " ".join(f'"{w}"' for w in words)
```

Кожне слово в лапках — тоді будь-який текст шукається буквально.

## Ранжування і сніпети

```sql
SELECT m.id, m.session_id, m.role, m.created_at,
       snippet(messages_fts, 0, '«', '»', '…', 20)
FROM messages_fts
JOIN messages m ON m.id = messages_fts.rowid
WHERE messages_fts MATCH ?
ORDER BY rank
LIMIT ?
```

`ORDER BY rank` — це BM25, стандартна міра релевантності пошукових рушіїв.
`snippet()` повертає фрагмент із підсвіченим збігом, а не все повідомлення.

## Опис інструмента

```
"Знайти, що обговорювалося в минулих сесіях. Пам'ять MEMORY.md коротка
й містить лише головне; тут — повний архів усіх розмов.
Використовуй, коли користувач посилається на щось раніше
('як ми домовились', 'той баг', 'минулого разу')… Пошук безкоштовний."
```

Фрази-тригери в описі важливі: без них модель не здогадується, що «той баг»
— це привід шукати в архіві.

## Перевірити

```
› Домовились: баг із таймзонами в планувальнику чинимо наступного тижня.
› /quit
› .venv/bin/python -m devmate.cli
› Що ми вирішили щодо того багу з таймзонами?
  [session_search] → знаходить у минулій сесії
› /search таймзони
  4 збігів за 0.6 мс, 0 викликів моделі
```
