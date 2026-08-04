"""Налаштування блоку. Це `../01_memory/devmate/config.py`, ужатий до потрібного.

Корпус, вектори і `scan()` не дублюються: `sys.path` веде в сусідні демо —
той самий прийом, яким `../02_rag/r5_poisoned_corpus.py` підключає `scan()`.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # demo_example/langgraph
sys.path.insert(0, str(ROOT.parent / "02_rag"))           # corpus.py + vectors.json

load_dotenv(ROOT.parent / ".env")                      # .env спільний з рештою демо

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
USER_ID = os.getenv("DEVMATE_USER", "boris")

DB_PATH = ROOT / "devmate_lg.db"   # чекпоінти; переживає перезапуск процесу
EMBED_DIMS = 1024                  # bge-m3, як у ../02_rag/vectors.json
MAX_ATTEMPTS = 2                   # бюджет внутрішнього циклу (RAG-підграф)
RECURSION_LIMIT = 25               # бюджет зовнішнього циклу (агент)

if not API_KEY:
    raise SystemExit("Немає OPENAI_API_KEY. Скопіюйте ../.env.example у ../.env.")


def chat_model():
    """Одна модель на всіх: і зовнішній агент, і вузли підграфа.

    Модель береться з `LLM_MODEL`, а не зашита рядком, як у конспекті
    (`04:1053`, `gpt-5.2-chat-latest`): провайдер у нас інший.
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY, temperature=0)
