"""Історія всіх сесій у SQLite з повнотекстовим пошуком.

Другий тип пам'яті, протилежний до MEMORY.md за всіма властивостями:

    MEMORY.md          історія сесій
    ~800 токенів       без обмежень
    завжди в промпті   тільки на запит
    курує модель       пишеться саме
    коштує токени      коштує ~0

Пошук робить SQLite, а не модель: жодного виклику LLM, жодних ембедингів.
"""

import sqlite3
from datetime import datetime

from .config import ROOT

DB_PATH = ROOT / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Індекси не зберігають текст удруге (content=''), а посилаються на messages.

-- Пошук за словами. Швидкий і точний, але слово має збігтися повністю.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='unicode61'
);

-- Пошук за трилітерними фрагментами. Потрібен через словозміну:
-- «таймзони» і «таймзонами» — різні слова для першого індексу, але
-- спільних тригам у них достатньо. Ціна — більший індекс.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_trigram USING fts5(
    content, content='messages', content_rowid='id', tokenize='trigram'
);

-- Тригери тримають обидва індекси в синхроні з таблицею.
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
    INSERT INTO messages_trigram(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO messages_trigram(messages_trigram, rowid, content)
    VALUES ('delete', old.id, old.content);
END;
"""


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")  # читання не блокує запис
    db.executescript(SCHEMA)
    return db


_db = _connect()


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def save(session_id: str, role: str, content: str) -> None:
    if not content.strip():
        return
    _db.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
        (session_id, role, content, datetime.now().isoformat(timespec="seconds")),
    )
    _db.commit()


def _fts_query(text: str) -> str:
    """Екранує запит користувача.

    У FTS5 своя мова запитів, де `-`, `*`, `"` мають особливий сенс.
    Кожне слово беремо в лапки — тоді будь-який текст шукається буквально.
    """
    words = [w.replace('"', "") for w in text.split() if w.strip()]
    return " ".join(f'"{w}"' for w in words)


def _stem(word: str) -> str:
    """Грубо відкидає закінчення.

    Тригамний індекс шукає підрядок, а «таймзони» не є підрядком
    «таймзонами». Обрізавши два символи, отримуємо спільну основу.
    Це не морфологія, але для пошуку по власному архіву вистачає.
    """
    word = word.strip(".,!?;:()[]\"'").lower()
    return word[:-2] if len(word) > 5 else word


def _query_index(index: str, match: str, limit: int) -> list[tuple]:
    """Один запит до індексу. Ранжування — BM25, як у пошукових рушіях."""
    return _db.execute(
        f"""
        SELECT m.id, m.session_id, m.role, m.created_at,
               snippet({index}, 0, '«', '»', '…', 20)
        FROM {index}
        JOIN messages m ON m.id = {index}.rowid
        WHERE {index} MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()


def search(query: str, limit: int = 5) -> list[dict]:
    """Пошук по всіх сесіях: спершу за словами, потім за фрагментами.

    Точні збіги цінніші, тому вони йдуть першими. Тригамний індекс
    підключається, лише якщо словами знайшлося замало — він знаходить
    інші форми слова, але й більше зайвого.
    """
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

    return [
        {"session": r[1], "role": r[2], "at": r[3], "excerpt": r[4]}
        for r in rows[:limit]
    ]


def stats() -> tuple[int, int]:
    """Скільки повідомлень і сесій накопичено."""
    return _db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM messages"
    ).fetchone()
