"""Спільна основа для трьох демо: CrewAI, Microsoft Agent Framework, Google ADK.

Тут лежить усе, що НЕ залежить від фреймворку:

* модель і ключ — один `GOOGLE_API_KEY` на всі три демо;
* домен — тікет підтримки про подвійне списання;
* інструменти — дві звичайні Python-функції;
* друк метрик — щоб порівнювати фреймворки не на око, а за цифрами.

Головна думка, заради якої цей файл існує окремо: **інструмент — це звичайна
Python-функція**. Усі три фреймворки беруть ті самі `get_payments` і `refund`
нижче. Відрізняється лише обгортка, і саме її ми порівнюємо на лекції.

Перевірка, що середовище живе:  .venv/bin/python common.py
"""
import logging
import os
import warnings
from dataclasses import dataclass, field

from dotenv import load_dotenv

# ── Ключ і модель ───────────────────────────────────────────────────────────
# .env лежить поруч; .env.local має пріоритет (зручно для локальних прогонів).
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
load_dotenv(os.path.join(_HERE, ".env.local"), override=True)

assert os.getenv("GOOGLE_API_KEY"), (
    "Встановіть GOOGLE_API_KEY у .env — ключ безкоштовно тут: "
    "https://aistudio.google.com/apikey"
)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Одного GOOGLE_API_KEY вистачає на всі три демо: під кожним фреймворком той
# самий SDK google-genai, який читає цю змінну. Окремий GEMINI_API_KEY ставити
# НЕ треба: коли задані обидва, SDK попереджає про це у виводі й лише шумить.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
# Телеметрія CrewAI малює банер після кожного прогону — на лекції це заважає.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
# Клієнт Gemini попереджає про automatic function calling на кожному прогоні —
# для демо це нічого не змінює, а на екрані заважає читати вивід.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
# ADK позначає частину своїх фіч експериментальними і пише про це попередження
# на кожен інструмент. А от DeprecationWarning НЕ глушимо: на кроці 2 демо ADK
# воно нам якраз потрібне — це і є розмова про строк життя API.
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")

# ── Домен: один на всі три демо ─────────────────────────────────────────────
# Домен навмисно один. Змінна, яку ми досліджуємо на лекції, — фреймворк,
# і тільки він. Якби ще й задача щоразу мінялась, порівнювати було б нічого.
CUSTOMER_ID = "C-1042"

TICKET = (
    "Клієнт C-1042 пише: «У мене подвійне списання з картки за березень. "
    "49.99 USD списалося двічі. Поверніть гроші.»"
)

# «База даних» платежів — детермінована, щоб демо не залежало від мережі
# і давало однаковий вхід на кожному прогоні.
_PAYMENTS = {
    "C-1042": [
        {"id": "PAY-3001", "date": "2026-03-04", "amount": 49.99, "status": "settled"},
        {"id": "PAY-3002", "date": "2026-03-04", "amount": 49.99, "status": "settled"},
        {"id": "PAY-2890", "date": "2026-02-04", "amount": 49.99, "status": "settled"},
    ]
}

_REFUNDED: set[str] = set()

# Ліміт, вище якого повернення вимагає людини. Знадобиться там, де показуємо
# guardrail: сам ліміт — це бізнес-правило, а не властивість фреймворку.
REFUND_LIMIT_USD = 100.0


def get_payments(customer_id: str) -> str:
    """Повертає список платежів клієнта за останні місяці.

    Args:
        customer_id: Ідентифікатор клієнта, наприклад C-1042.
    """
    rows = _PAYMENTS.get(customer_id, [])
    if not rows:
        return f"Платежів для {customer_id} не знайдено."
    return "\n".join(
        f"{r['id']} | {r['date']} | {r['amount']:.2f} USD | {r['status']}" for r in rows
    )


def refund(payment_id: str) -> str:
    """Оформлює повернення коштів за вказаним платежем.

    Args:
        payment_id: Ідентифікатор платежу, наприклад PAY-3002.
    """
    if payment_id in _REFUNDED:
        return f"Повернення за {payment_id} вже оформлене раніше."
    _REFUNDED.add(payment_id)
    return f"Повернення за {payment_id} оформлено. Кошти надійдуть за 3-5 днів."


TOOLS = [get_payments, refund]


# ── Метрики: чим ми порівнюємо фреймворки ───────────────────────────────────
@dataclass
class Metrics:
    """Скільки коштував прогін.

    Головна цифра лекції — `calls`. Саме вона показує ціну координації:
    динамічний вибір маршруту (менеджер, selector) додає виклики LLM, яких
    у детермінованому пайплайні просто немає.
    """

    framework: str
    step: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    notes: list[str] = field(default_factory=list)

    def report(self) -> None:
        print("\n\n\n" + "─" * 68)
        print(f"МЕТРИКИ · {self.framework} · {self.step}")
        print(f"  викликів LLM       : {self.calls}")
        print(f"  токенів (prompt)   : {self.prompt_tokens}")
        print(f"  токенів (completion): {self.completion_tokens}")
        for note in self.notes:
            print(f"  • {note}")
        print("─" * 68)


def banner(framework: str, step: str, idea: str) -> None:
    """Однакова шапка в усіх кроках — щоб на екрані було видно, де ми."""
    print("\n" + "=" * 68)
    print(f"{framework} · {step}")
    print(f"Ідея кроку: {idea}")
    print("=" * 68)


if __name__ == "__main__":
    print("Модель :", MODEL)
    print("Ключ   : GOOGLE_API_KEY знайдено")
    print("\nТікет:", TICKET)
    print("\nІнструмент get_payments(C-1042):")
    print(get_payments(CUSTOMER_ID))
    print("\nІнструмент refund(PAY-3002):")
    print(refund("PAY-3002"))
