"""Усе, що ми писали руками (006-012), — в одному виклику create_agent.

    pip install langchain langchain-openai

    python 016_langchain_create_agent.py                  # зі структурованим виводом
    STRUCTURED=0 python 016_langchain_create_agent.py     # без нього (див. примітку нижче)

ПРИМІТКА ПРО ПРОТІКАННЯ АБСТРАКЦІЇ (перевірено наживо, гарний момент для лекції).
response_format=ToolStrategy(...) під капотом надсилає провайдеру tool_choice="required".
Не кожна модель за шлюзом це вміє: наприклад, на 'oc/deepseek-v4-flash-free' апстрім
відповідає 400 Bad Request, а на 'kr/claude-haiku-4.5' усе працює. Тобто уніфікований
інтерфейс ховає різницю провайдерів, але не скасовує її — вона просто вилазить пізніше
і в менш очевидному місці. Лікується вибором моделі або STRUCTURED=0:

    LLM_MODEL=kr/claude-haiku-4.5 python 016_langchain_create_agent.py

Що зникло з коду порівняно з 010:
  - ручний опис TOOLS з JSON Schema   -> схема будується з типів і docstring
  - словник TOOL_FUNCTIONS і диспетч  -> усередині графа
  - цикл while + append у messages    -> усередині графа
  - ручна валідація фінального JSON   -> response_format

Що НЕ зникло і його все одно писати самому: доменні запобіжники з 011
(allowlist бізнес-правил, no-progress detector, ліміт саме наших ітерацій).
Фреймворк дає цикл, а не надійність.
"""

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

load_dotenv()

RETURN_WINDOW_DAYS = 30


class ReturnItem(BaseModel):
    order_id: str
    days_since_delivery: int
    return_allowed: bool


class ReturnReport(BaseModel):
    items: list[ReturnItem]
    summary: str


def days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1003", "status": "доставлено", "delivered_at": days_ago(1)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


# Звичайні Python-функції: декоратор @tool не обов'язковий.
# JSON Schema збирається з анотацій типів, опис інструмента — з docstring.
def query_orders(status: str) -> list[dict]:
    """Отримати список замовлень із заданим статусом ('повернення' або 'доставлено')."""
    return [o for o in ORDERS if o["status"] == status]


def check_return_policy(order_id: str) -> dict:
    """Перевірити, чи можна ще повернути замовлення за його ідентифікатором (напр. 'A-1001')."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}

    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {
        "order_id": order_id,
        "days_since_delivery": days,
        "return_window_days": RETURN_WINDOW_DAYS,
        "return_allowed": days <= RETURN_WINDOW_DAYS,
    }


AGENT_SPEC = f"""
Ти агент підтримки інтернет-магазину.
МЕТА: для кожного замовлення зі статусом 'повернення' визначити, чи вкладається воно
у вікно повернення ({RETURN_WINDOW_DAYS} днів).
ПОЛІТИКИ: спочатку query_orders, потім check_return_policy окремо для кожного знайденого.
ОБМЕЖЕННЯ: лише читання; дані брати виключно з інструментів.
NON-GOALS: не оформлювати повернення, не писати клієнту.
КРИТЕРІЙ ЗАВЕРШЕННЯ: для кожного замовлення зі списку є результат перевірки.
"""

# Модель задаємо ОБ'ЄКТОМ, а не рядком "openai:...", щоб явно бачити,
# куди йде запит: наш шлюз або локальна Ollama — те саме, що і в решті демо.
model = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["OPENAI_BASE_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
    temperature=0,
)

# ToolStrategy задаємо явно: він працює через звичайний tool calling.
# Якщо передати голий ReturnReport, LangChain обирає стратегію сам і може спробувати
# нативний structured output, якого за шлюзом чи в Ollama може не бути.
structured = os.getenv("STRUCTURED", "1") == "1"

agent = create_agent(
    model=model,
    tools=[query_orders, check_return_policy],
    system_prompt=AGENT_SPEC,
    response_format=ToolStrategy(ReturnReport) if structured else None,
)

result = agent.invoke(
    {"messages": [("user", "Які замовлення на поверненні ще можна повернути?")]}
)

# Той самий лог Think -> Act -> Observe, що і в 009, лише під іншими назвами.
for message in result["messages"]:
    print(f"[{message.type.upper()}] {message.content or ''}"[:300])
    for call in getattr(message, "tool_calls", []) or []:
        print(f"    [TOOL_CALL] {call['name']}({call['args']})")
print()

if structured:
    # Валідований екземпляр ReturnReport — те саме, що в 010 ми робили руками.
    report: ReturnReport = result["structured_response"]
    print(f"[FINAL_ANSWER] {report.summary}\n")
    for item in report.items:
        print(f"  {item.order_id}: {item.days_since_delivery} дн., дозволено={item.return_allowed}")
else:
    print(f"[FINAL_ANSWER] {result['messages'][-1].content}")

# Під капотом create_agent — скомпільований граф LangGraph. Звідси безкоштовно
# з'являються checkpointing, streaming, human-in-the-loop і можливість вставити
# цього агента вузлом у більший граф. Все це — теми лекцій 2 і 4.
