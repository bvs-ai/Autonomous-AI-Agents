"""Один виклик LLM для всіх демо RAG плюс лічильник викликів.

Лічильник тут не для краси: на ньому будується порівняння r2 і r3 —
traditional RAG коштує один виклик, agentic кілька.

Модель — reasoning: поруч із `content` вона повертає `reasoning_content`.
Читаємо строго `content`, інакше в промпт поїдуть роздуми моделі.
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
calls = 0


class LLMUnavailable(RuntimeError):
    """Провайдер не відповів. Падати трейсом при аудиторії не можна."""


def call_llm(messages: list[dict], **kwargs) -> str:
    global calls
    calls += 1
    try:
        r = requests.post(
            f"{os.environ['OPENAI_BASE_URL']}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": MODEL, "stream": False, "temperature": 0,
                  "messages": messages, **kwargs},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except KeyError:
        raise LLMUnavailable(f"Провайдер відповів без content: {r.text[:200]}") from None
    except Exception as e:
        raise LLMUnavailable(
            f"{os.environ.get('OPENAI_BASE_URL')} недоступний ({type(e).__name__}). "
            f"Перевірте .env") from None


def cost() -> str:
    return f"[COST] викликів LLM: {calls}"
