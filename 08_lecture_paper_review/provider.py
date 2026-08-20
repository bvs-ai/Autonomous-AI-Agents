"""Єдине місце, де демо обирає LLM-провайдера (m3, m4b, m6, m7).

.env поруч зі скриптами:

    GOOGLE_API_KEY=...                  # https://aistudio.google.com/apikey
    GEMINI_MODEL=gemini-3.5-flash-lite  # необовʼязково

Будь-який OpenAI-сумісний шлюз:

    LLM_PROVIDER=openai
    OPENAI_BASE_URL=... / OPENAI_API_KEY=... / LLM_MODEL=...
"""
import os

from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv(".env")

PROVIDER = os.getenv("LLM_PROVIDER") or ("google" if os.getenv("GOOGLE_API_KEY") else "openai")


def make_llm():
    """Чат-модель із підтримкою tool calling."""
    if PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # max_retries: у безкоштовного тарифу жорсткий ліміт запитів за хвилину.
        return ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                                      max_retries=6)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=os.environ["LLM_MODEL"],
                      base_url=os.environ["OPENAI_BASE_URL"],
                      api_key=SecretStr(os.environ["OPENAI_API_KEY"]))
