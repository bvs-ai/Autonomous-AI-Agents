"""КРОК 1. Імпорти, налаштування логування та ініціалізація моделі.

Відповідає розділу «Крок 1» практикуму. Усі наступні кроки імпортують звідси
`llm`, `logger` та хелпер `get_text`.

Запуск:  .venv/bin/python step1_setup.py
"""
import logging
import os
import warnings

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# ── Налаштування логування ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")
# Бібліотеки LangChain/Chroma дуже балакучі — прибираємо їхній шум із демо
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.ERROR)
# gemini-3.5-flash-lite має фіксовані параметри семплінгу і сам ігнорує temperature,
# попереджаючи про це при кожному виклику. Прибираємо цей шум із виводу демо.
warnings.filterwarnings("ignore", message=".*fixed sampling defaults.*")
warnings.filterwarnings("ignore", message=".*langchain-community.*")

# ── Завантаження API-ключа ──
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
assert os.getenv("GOOGLE_API_KEY"), "Встановіть GOOGLE_API_KEY у .env або змінних середовища"

# У конспекті стоїть gemini-2.5-pro; для лекції беремо швидшу та дешевшу
# gemini-3.5-flash-lite. Модель змінюється однією змінною у .env.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# ── Ініціалізація моделі ──
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0.2,
    max_output_tokens=1024,
    timeout=60,
    # На безкоштовному тарифі легко впертись у ліміт запитів за хвилину:
    # Plan-and-Execute робить виклики пачками. Ретраї рятують демо від 429.
    max_retries=6,
)


def get_text(content) -> str:
    """Gemini повертає message.content СПИСКОМ блоків, а не рядком.

    Це та сама пастка, про яку попереджає конспект після Кроку 3: код,
    написаний під OpenAI, мовчки друкує «[{'type': 'text', ...}]» замість
    відповіді. Хелпер зводить обидва формати до звичайного тексту.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content)


if __name__ == "__main__":
    print("✅ Середовище підготовлено. Модель:", llm.model)
    # Найпростіша перевірка, що ключ живий і модель відповідає
    reply = llm.invoke("Відповідай українською. Скажи одним реченням, що ти працюєш.")
    print("🤖", get_text(reply.content))
