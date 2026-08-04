"""Зовнішній цикл. Це `../01_memory/devmate/agent.py` — 163 рядки tool-calling — одним викликом.

Три цикли, і вони різні:

    1. розмова        — `create_react_agent`, стан `messages`, живе в чекпоінтері
    2. добування      — `rag.py`, стан `RAGState`, живе один виклик інструмента
    3. сесії          — новий `thread_id`: історія порожня, факти в store на місці

Звʼязок циклів 1 і 2 — рівно одна функція `search_kb`: скомпільований граф це
звичайний `Runnable`, тому виклик підграфа з інструмента — просто виклик функції.
Наслідок, заради якого так і зроблено: рефлексія спалює 3–6 викликів моделі, і
**жоден не потрапляє в контекст агента** — нагору піднімається один `ToolMessage`.
Це та сама гігієна контексту, що й у памʼяті (`04:800`, «лише стабільні факти»),
але застосована до результату інструмента. Ціна — траєкторія не видна ззовні,
тому підграф веде `history`, а REPL показує її по `/trace`.
"""
import sqlite3
import subprocess
import sys
import warnings
from dataclasses import dataclass

from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.runtime import get_runtime
from langgraph.store.memory import InMemoryStore

from . import rag
from .config import DB_PATH, EMBED_DIMS, ROOT, USER_ID, chat_model
from .vector_store import TENANT

# `.config` імпортується першим: саме він кладе `../rag` у `sys.path`.
from corpus import embed  # noqa: E402  — вектори з кешу, мережі не треба
from .hooks import recall_and_trim
from .memory_tools import forget, remember, seed

# Конспект (`04:1053`) пише `from langchain.agents import create_agent` — це
# інший пакет із іншим API (middleware замість хуків). Нам потрібен саме
# `pre_model_hook`, тому беремо `langgraph.prebuilt`; попередження про
# переїзд глушимо, щоб не миготіло на екрані при аудиторії.
warnings.filterwarnings("ignore", message=".*create_react_agent has been moved.*")
# Нульовий вектор (текст поза кешем, див. `embed_texts`) дає ділення на нуль у
# косинусі. Результат правильний — «не схоже ні на що», — але numpy пише про це
# на екран посеред демо.
warnings.filterwarnings("ignore", message=".*invalid value encountered in divide.*")
from langgraph.prebuilt import create_react_agent  # noqa: E402

SYSTEM = (
    "Ти DevMate — помічник розробника цього проєкту. Відповідай стисло, українською.\n"
    "- питання про проєкт, його нотатки й рішення → спочатку виклич search_kb;\n"
    "- користувач повідомив стійкий факт про себе або проєкт → виклич remember;\n"
    "- просить забути → forget; просить прогнати тести → run_tests.\n"
    "Не вигадуй фактів про проєкт: якщо search_kb не дав відповіді, скажи це прямо."
)

RAG_GRAPH = rag.build_rag_graph()   # компілюється один раз


@dataclass
class Context:
    """Хто питає. Їде поруч зі станом, а не в ньому (`04:792`).

    `tenant` звідси йде у фільтр векторного сховища (`vector_store.search`).
    Саме тому він тут, а не в стані: дозволи не повинні їхати в чекпоінті
    діалогу, який модель до того ж уміє переписувати.
    """

    user_id: str = USER_ID
    tenant: str = TENANT


@tool
def search_kb(query: str) -> str:
    """Знайти відповідь у нотатках проєкту. Питання передавай дослівно, як спитав
    користувач. Повертає відповідь із цитатами [d1]."""
    # Тенант підграфу передаємо явно, з рантайму агента: модель не бере участі
    # у виборі того, що їй дозволено бачити.
    try:
        tenant = get_runtime().context.tenant
    except Exception:
        tenant = TENANT
    out = RAG_GRAPH.invoke({"query": query, "attempts": 0, "tenant": tenant})
    rag.LAST_TRACE[:] = out["history"]        # для /trace
    return f"{out['answer']}\n\nДжерела: {', '.join(out['citations']) or '—'}"


@tool
def run_tests() -> str:
    """Прогнати тести проєкту (pytest -q)."""
    # Через `sys.executable -m`, а не голим `pytest`: якщо його не поставлено,
    # інструмент має повернути моделі текст помилки, а не впасти винятком.
    done = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                          check=False, capture_output=True, text=True, timeout=120)
    return f"exit={done.returncode}\n{done.stdout}{done.stderr}"[:2000]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Ембединги для store — офлайновий `embed()` з `../02_rag/corpus.py`.

    `IndexConfig.embed` приймає callable, тому семантичний пошук у памʼяті
    працює на кешованих векторах, без мережі. Текст, якого в кеші немає (свіжий
    факт із `remember`) або текст запиту поза кешем, отримує нульовий вектор:
    запис зберігається й видно його в `/memory`, але семантично не знайдеться,
    поки кеш не перерахують (`python ../02_rag/build_vectors.py`). Падати через це
    не можна: пригадування — покращення, а не умова роботи.
    """
    out = []
    for text in texts:
        try:
            out.append(list(embed(text)))
        except Exception:
            print(f"[EMBED] немає вектора для {text[:40]!r} — семантика тут не працює")
            out.append([0.0] * EMBED_DIMS)
    return out


def build():
    """Агент, store і чекпоінтер. Один виклик замість трьох модулів DevMate."""
    # `from_conn_string` — контекстний менеджер, він закриє зʼєднання на виході
    # з `with` (`04:647`). REPL живе всю сесію, тому зʼєднання створюємо самі:
    # рівно те, що робить менеджер усередині, без чужого часу життя.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()

    store = InMemoryStore(index={"embed": embed_texts, "dims": EMBED_DIMS, "fields": ["text"]})
    seed(store, USER_ID)

    agent = create_react_agent(
        chat_model(),
        tools=[search_kb, remember, forget, run_tests],
        prompt=SYSTEM,
        pre_model_hook=recall_and_trim,
        context_schema=Context,  # user_id не в state
        checkpointer=saver,      # SqliteSaver, не InMemorySaver: переживає рестарт
        store=store,             # памʼять поверх сесій
    )
    return agent, store
