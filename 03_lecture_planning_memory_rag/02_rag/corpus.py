"""Спільний корпус і два пошуки для демо RAG.

Корпус — це нотатки й фрагменти минулих сесій нашого агента (див. демо
`../01_memory/`). Там архів шукався повнотекстово, по словах. Тут ми беремо
той самий матеріал і показуємо, де такий пошук ламається і чим його
замінюють.

Два пошуки навмисно лежать поруч:

    search_keyword  — збіг слів, як FTS5 у `01_memory/devmate/sessions.py`
    search_semantic — близькість векторів, основа будь-якого RAG

Вектори пораховані заздалегідь і лежать у `vectors.json` (див.
`build_vectors.py`). На лекції жодного мережевого виклику для пошуку не
відбувається: миттєво й однаково при кожному запуску. Якщо тексту немає в
кеші — рахуємо живцем через `EMBED_BASE_URL`, і лише тоді потрібна мережа.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
VECTORS_PATH = Path(__file__).with_name("vectors.json")

# ── Корпус ────────────────────────────────────────────────────────────────
# `id` — стабільна адреса джерела: саме її показує цитата в r2.
DOCS = [
    {"id": "d1", "text": "Checkpointer зберігає знімок стану після кожного кроку — "
                         "агент продовжує з місця зупинки, а не з нуля."},
    {"id": "d2", "text": "Планувальник звітів рахує дедлайни з таймзонами користувача."},
    {"id": "d3", "text": "Тести проєкту запускаються командою pytest -q."},
    {"id": "d4", "text": "Старий раннер на unittest більше не підтримується — "
                         "ним тести не запускати."},
    {"id": "d5", "text": "Reranking через cross-encoder переставляє знайдене: "
                         "vector store дає 20-50 кандидатів, reranker лишає 3-5."},
    {"id": "d6", "text": "Plan-and-execute відділяє планування від виконання: "
                         "сильна модель планує рідко, дешева виконує кроки."},
    {"id": "d7", "text": "Довга історія повідомлень стискається конспектом, "
                         "але голова і хвіст діалогу лишаються недоторканими."},
    {"id": "d8", "text": "Python — мова програмування загального призначення."},
    {"id": "d9", "text": "Кожен запит до сховища обовʼязково фільтрується по tenant_id, "
                         "інакше дані одного клієнта потраплять іншому."},
]


class EmbedUnavailable(RuntimeError):
    """Тексту немає в кеші, а порахувати вектор нема чим."""


# ── Ембединги ─────────────────────────────────────────────────────────────
def norm(text: str) -> str:
    """Ключ кешу: без регістру й зайвих пробілів, апострофи зведені."""
    return re.sub(r"\s+", " ", text.strip().lower()).replace("ʼ", "'").replace("’", "'")


@lru_cache(maxsize=1)
def _cache() -> dict[str, list[float]]:
    if not VECTORS_PATH.exists():
        return {}
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


def embed_live(text: str) -> list[float]:
    """Порахувати вектор через API. Ollama або будь-який OpenAI-сумісний."""
    if "/v1" in EMBED_BASE_URL:
        url, payload = f"{EMBED_BASE_URL}/embeddings", {"model": EMBED_MODEL, "input": text}
        key = os.environ.get("EMBED_API_KEY", "")
        r = requests.post(url, json=payload, timeout=60,
                          headers={"Authorization": f"Bearer {key}"} if key else {})
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]
    r = requests.post(f"{EMBED_BASE_URL}/api/embed", timeout=60,
                      json={"model": EMBED_MODEL, "input": text})
    r.raise_for_status()
    return r.json()["embeddings"][0]


@lru_cache(maxsize=256)
def embed(text: str) -> tuple[float, ...]:
    """Текст -> вектор. Спершу кеш `vectors.json`, і лише потім мережа."""
    cached = _cache().get(norm(text))
    if cached is not None:
        return tuple(cached)
    try:
        return tuple(embed_live(text))
    except Exception as e:  # мережі нема — кажемо це людською мовою, не трейсом
        raise EmbedUnavailable(
            f"Немає вектора для {text!r}: у кеші його нема, "
            f"а {EMBED_BASE_URL} недоступний ({type(e).__name__}). "
            f"Порахуйте кеш: python build_vectors.py") from None


def cosine(a: tuple, b: tuple) -> float:
    """Косинус між векторами. Нормалізації немає — рахуємо чесно."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)


# ── Два пошуки ────────────────────────────────────────────────────────────
# Службові слова викидаємо, як це робить будь-який повнотекстовий індекс:
# інакше «і» чи «не» вважалися б збігом і давали б випадкові влучання.
STOPWORDS = {"і", "й", "а", "але", "не", "з", "із", "зі", "у", "в", "на", "до",
             "по", "за", "як", "якщо", "що", "щоб", "це", "той", "все", "усе",
             "чи", "же", "б", "бути", "має", "після", "ним", "його"}


def _words(text: str) -> set[str]:
    words = {w.strip(".,!?;:()[]«»\"'-—").lower() for w in text.split()}
    return {w for w in words if w and w not in STOPWORDS}


def search_keyword(query: str, k: int = 3) -> list[dict]:
    """Збіг слів. Рівно те, що вміє словниковий індекс FTS5.

    «Таймзони» не дорівнює «таймзонами», тому потрібної нотатки він не
    знайде — це та сама поразка, що й у `/search` демо памʼяті.
    """
    q = _words(query)
    scored = [(len(q & _words(d["text"])), d) for d in DOCS]
    return [d for n, d in sorted(scored, key=lambda p: -p[0]) if n > 0][:k]


def search_semantic(query: str, k: int = 3, docs: list[dict] | None = None
                    ) -> list[tuple[float, dict]]:
    """Близькість векторів. Слова можуть не збігтися жодного разу."""
    qv = embed(query)
    scored = [(cosine(qv, embed(d["text"])), d) for d in (docs or DOCS)]
    return sorted(scored, key=lambda p: -p[0])[:k]
