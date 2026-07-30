"""Це БУКВАЛЬНО той самий create_agent, що ви вже запускали в 016 лекції 1 --
з тим самим AGENT_SPEC. Тоді він був фіналом («усе, що ми писали руками, --
в одному виклику»). Тепер він стартова точка, і ми називаємо цикл усередині
нього своїм іменем: це ReAct.

Тому дивимось не на відповідь (її ми вже бачили), а на САМ ГРАФ:
  1. структура: два вузли (model, tools) і умовне ребро між ними --
     get_graph().draw_mermaid() малює її прямо з обʼєкта, без діаграм руками;
  2. виконання по кроках через .stream(): кожен крок -- спрацювання ОДНОГО
     вузла, тобто буквально Action (вузол model) і Observation (вузол tools).
     Thought у сучасних tool-calling API неявний -- він «усередині» рішення
     моделі викликати інструмент, окремим текстом його немає.

Саме ці переходи в 018 ми перехопимо своїм StopController, а вузол tools
замінимо на safe_tool_node. Тобто «агент» -- не магія, а граф, у який можна
втрутитися.

І третє -- фінальний structured output (див. кінець файлу). У 016 лекції 1 звіт
за схемою робив САМ агент через response_format=ToolStrategy(ReturnReport). Тут
той самий Pydantic-звіт збирається ОКРЕМИМ кроком ПІСЛЯ циклу, через
model.with_structured_output(). Різниця не косметична: ToolStrategy під капотом
шле провайдеру tool_choice="required", і на нашій моделі за шлюзом це 400 Bad
Request (у лекції 1 це лікували вибором kr/claude-haiku-4.5). with_structured_output
обходиться звичайним tool calling -- тому працює там, де ToolStrategy падає.
Загальне правило: чим менше вимог до рушія провайдера, тим переносніший агент.

Примітка про API: у LangGraph 1.0 create_react_agent з langgraph.prebuilt
оголошено застарілим саме на користь create_agent з langchain.agents. У багатьох
статтях і туторіалах ви ще зустрінете старий варіант -- це той самий граф.

Потребує заповненого .env і requirements_langgraph.txt.
"""

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from pydantic import BaseModel, Field

load_dotenv()

RETURN_WINDOW_DAYS = 30


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


ORDERS = [
    {"id": "A-1001", "status": "повернення", "delivered_at": days_ago(3)},
    {"id": "A-1002", "status": "повернення", "delivered_at": days_ago(45)},
    {"id": "A-1004", "status": "повернення", "delivered_at": days_ago(12)},
]


@tool
def query_orders(status: str) -> list[dict]:
    """Отримати список замовлень із заданим статусом ('повернення' або 'доставлено')."""
    return [o for o in ORDERS if o["status"] == status]


@tool
def check_return_policy(order_id: str) -> dict:
    """Перевірити, чи можна ще повернути замовлення за його ідентифікатором (напр. 'A-1001')."""
    order = next((o for o in ORDERS if o["id"] == order_id), None)
    if order is None:
        return {"error": f"Замовлення {order_id} не знайдено"}
    days = (date.today() - date.fromisoformat(order["delivered_at"])).days
    return {"order_id": order_id, "days_since_delivery": days, "return_allowed": days <= RETURN_WINDOW_DAYS}


# Той самий Agent Spec, що і в 012/016 лекції 1 -- контракт агента не змінюється
# від того, що ми розглядаємо його внутрішній цикл.
AGENT_SPEC = f"""
Ти агент підтримки інтернет-магазину.
МЕТА: визначити, чи вкладається замовлення у вікно повернення ({RETURN_WINDOW_DAYS} днів).
ПОЛІТИКИ: якщо номер замовлення відомий -- одразу check_return_policy.
ОБМЕЖЕННЯ: лише читання; дані брати виключно з інструментів.
"""

class ReturnItem(BaseModel):
    order_id: str
    days_since_delivery: int
    return_allowed: bool


class ReturnReport(BaseModel):
    """Той самий ReturnReport, що і в 010/016 лекції 1 -- контракт фінальної відповіді."""

    summary: str = Field(description="Стислий висновок українською")
    items: list[ReturnItem]


model = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["OPENAI_BASE_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
    temperature=0,
)

agent = create_agent(model=model, tools=[query_orders, check_return_policy], system_prompt=AGENT_SPEC)

if __name__ == "__main__":
    print("=== СТРУКТУРА ГРАФА ===")
    print("[MERMAID] (вставити в будь-який mermaid-рендерер)")
    print(agent.get_graph().draw_mermaid())

    print("=== ВИКОНАННЯ ПО ВУЗЛАХ ===")
    question = "Чи можна ще повернути замовлення A-1002?"
    final_text = ""
    for step, chunk in enumerate(agent.stream({"messages": [("user", question)]}), start=1):
        for node, update in chunk.items():
            message = update["messages"][-1]
            if node == "tools":
                print(f"[КРОК {step}] вузол 'tools' -> Observation: {message.content[:100]}")
            else:
                calls = [f"{c['name']}({c['args']})" for c in message.tool_calls]
                action = calls or "(немає tool_calls -> вихід з циклу, це фінальна відповідь)"
                print(f"[КРОК {step}] вузол '{node}' -> Action: {action}")
                if not calls:
                    final_text = message.content

    print("\nКожен крок -- один вузол. Умовне ребро після вузла LLM щоразу вирішує:")
    print("є tool_calls -> йдемо в 'tools', немає -> END. Це і є весь ReAct-цикл.")

    print("\n=== ФІНАЛЬНИЙ STRUCTURED OUTPUT ===")
    # Три рядки -- і вільний текст стає валідованим Pydantic-обʼєктом.
    # with_structured_output повертає Runnable, який під капотом прив'язує
    # ReturnReport як інструмент і розбирає відповідь у модель. Це ОКРЕМИЙ виклик
    # уже ПІСЛЯ ReAct-циклу -- граф про нього не знає (у домашці це буде окремий
    # вузол 'formatter' у StateGraph, підключений між вузлом model і END).
    formatter = model.with_structured_output(ReturnReport)
    report: ReturnReport = formatter.invoke(final_text)

    print(f"[FINAL_ANSWER] {report.summary}")
    for item in report.items:
        print(f"  {item.order_id}: {item.days_since_delivery} дн., дозволено={item.return_allowed}")
    print(f"\n[TYPE] {type(report).__name__} -- не рядок, а обʼєкт: report.items[0].return_allowed "
          f"= {report.items[0].return_allowed!r} ({type(report.items[0].return_allowed).__name__})")
