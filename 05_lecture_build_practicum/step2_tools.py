"""КРОК 2. Інструменти з Pydantic-схемами та валідацією.

П'ять інструментів: calculator, current_datetime, wikipedia_search, http_get,
file_write. Кожен має типізований вхід (BaseModel + field_validator), опис для
LLM та повертає JSON-рядок зі стандартним полем `status`.

Запуск:  .venv/bin/python step2_tools.py
"""
import json
import warnings
from datetime import datetime

import numexpr as ne
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

# langchain-community попереджає про свій sunset при кожному імпорті — прибираємо шум
warnings.filterwarnings("ignore", message=".*langchain-community.*")

# ══════════════════════════════════════════════════════════
# Pydantic-схеми інструментів
# ══════════════════════════════════════════════════════════


# ── Схема: калькулятор ──
class CalcInput(BaseModel):
    """Вхідні дані для калькулятора."""
    expression: str = Field(
        ..., description="Математичний вираз (числа, +, -, *, /, дужки, степені)",
        min_length=1, max_length=200
    )

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, v: str) -> str:
        allowed = set("0123456789+-*/().eE^ ,")
        if not all(ch in allowed for ch in v):
            raise ValueError(f"Неприпустимі символи у виразі: {v}")
        return v.strip()


# ── Схема: пошук у Wikipedia ──
class WikiInput(BaseModel):
    """Вхідні дані для пошуку в Wikipedia."""
    query: str = Field(..., description="Пошуковий запит", min_length=2, max_length=300)
    lang: str = Field(default="uk", description="Код мови (uk, en)")

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str) -> str:
        if v not in ("uk", "en", "de", "fr", "es"):
            raise ValueError(f"Непідтримувана мова: {v}")
        return v


# ── Схема: HTTP-запит ──
class HttpInput(BaseModel):
    """Вхідні дані для HTTP GET-запиту."""
    url: str = Field(..., description="URL для GET-запиту")
    timeout_sec: int = Field(default=10, ge=1, le=30, description="Таймаут у секундах")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL повинен починатися з http:// або https://")
        return v


# ── Схема: файлові операції (ризиковий інструмент) ──
class FileWriteInput(BaseModel):
    """Вхідні дані для запису у файл (ризикова операція)."""
    path: str = Field(..., description="Шлях до файлу")
    content: str = Field(..., description="Вміст для запису", max_length=10000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        # Захист від виходу за межі робочої директорії
        if ".." in v or v.startswith("/"):
            raise ValueError("Шлях не повинен містити '..' або починатися з '/'")
        return v


# ── Схема: поточна дата/час ──
class DateTimeInput(BaseModel):
    """Вхідні дані для отримання поточної дати/часу."""
    format: str = Field(
        default="datetime",
        description="Формат: 'date', 'time', 'datetime', 'day', 'iso'"
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        valid = {"date", "time", "datetime", "day", "iso"}
        if v not in valid:
            raise ValueError(f"Формат '{v}' не підтримується. Допустимі: {valid}")
        return v


# ══════════════════════════════════════════════════════════
# Реалізація інструментів
# ══════════════════════════════════════════════════════════


@tool(args_schema=CalcInput)
def calculator(expression: str) -> str:
    """Обчислює математичний вираз. Використовуй для арифметики, дужок, степенів."""
    try:
        # numexpr не розуміє '^' як степінь — переводимо у пайтонівське '**'
        result = ne.evaluate(expression.replace("^", "**"))
        val = result.item() if hasattr(result, "item") else result
        return json.dumps({"status": "ok", "expression": expression, "result": val})
    except Exception as e:
        return json.dumps({"status": "error", "expression": expression, "error": str(e)})


@tool(args_schema=DateTimeInput)
def current_datetime(format: str = "datetime") -> str:
    """Повертає поточну дату, час або день тижня у вказаному форматі."""
    now = datetime.now()
    days_ua = {0: "Понеділок", 1: "Вівторок", 2: "Середа", 3: "Четвер",
               4: "П'ятниця", 5: "Субота", 6: "Неділя"}
    mapping = {
        "date": now.strftime("%d.%m.%Y"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%d.%m.%Y %H:%M:%S"),
        "day": days_ua.get(now.weekday(), "?"),
        "iso": now.isoformat(),
    }
    return json.dumps({"status": "ok", "format": format,
                       "value": mapping.get(format, mapping["datetime"])})


@tool(args_schema=WikiInput)
def wikipedia_search(query: str, lang: str = "uk") -> str:
    """Шукає стислу інформацію у Wikipedia. Використовуй для фактів, біографій, визначень."""
    import wikipedia as wikipedia_lib
    from langchain_community.utilities import WikipediaAPIWrapper

    # Без власного User-Agent Wikipedia періодично відповідає порожнім тілом,
    # і бібліотека падає з «Expecting value: line 1 column 1». Це не помилка
    # агента, але виглядає саме як «інструмент зламався» — тому ставимо User-Agent.
    wikipedia_lib.set_user_agent("AgentBot/1.0 (LangGraph course demo)")

    # wiki_client передаємо явно: у схемі це обов'язкове поле, і хоча
    # model_validator підставив би модуль сам, перевірка типів цього не бачить.
    wiki = WikipediaAPIWrapper(wiki_client=wikipedia_lib, lang=lang,
                               top_k_results=1, doc_content_chars_max=1000)
    try:
        result = wiki.run(query)
        if not result or result.startswith("No good Wikipedia Search Result"):
            return json.dumps({"status": "not_found", "query": query}, ensure_ascii=False)
        return json.dumps({"status": "ok", "query": query, "summary": result[:1000]},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "query": query, "error": str(e)},
                          ensure_ascii=False)


@tool(args_schema=HttpInput)
def http_get(url: str, timeout_sec: int = 10) -> str:
    """Виконує HTTP GET-запит. Використовуй для отримання даних з публічних API."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgentBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read(2000).decode("utf-8", errors="replace")
            return json.dumps({"status": "ok", "url": url, "code": resp.status,
                               "body": data[:1500]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "url": url, "error": str(e)})


@tool(args_schema=FileWriteInput)
def file_write(path: str, content: str) -> str:
    """Записує вміст у файл. РИЗИКОВА ОПЕРАЦІЯ — потребує підтвердження оператора."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"status": "ok", "path": path,
                           "bytes_written": len(content.encode("utf-8"))})
    except Exception as e:
        return json.dumps({"status": "error", "path": path, "error": str(e)})


# Список усіх інструментів
all_tools = [calculator, current_datetime, wikipedia_search, http_get, file_write]
# Безпечні інструменти (без file_write)
safe_tools = [calculator, current_datetime, wikipedia_search, http_get]


if __name__ == "__main__":
    print("✅ Pydantic-схеми CalcInput, WikiInput, HttpInput, FileWriteInput, "
          "DateTimeInput визначено.")
    print("✅ Інструменти створено:", [t.name for t in all_tools])

    # Виклик інструментів «руками», без LLM — саме так їх варто налагоджувати
    print("\n— calculator:", calculator.invoke({"expression": "1234 * 5678 + 99"}))
    print("— current_datetime:", current_datetime.invoke({"format": "day"}))
    print("— http_get:", http_get.invoke({"url": "https://api.github.com/zen"})[:120])

    # Валідація зупиняє небезпечний виклик ДО виконання коду інструмента
    try:
        calculator.invoke({"expression": "__import__('os').system('ls')"})
    except Exception as e:
        print("\n🛡️  Валідація відхилила ін'єкцію:", type(e).__name__)
    try:
        FileWriteInput(path="../etc/passwd", content="hack")
    except Exception as e:
        print("🛡️  Валідація відхилила path traversal:", type(e).__name__)
