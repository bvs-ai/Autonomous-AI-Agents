"""r4 — durable execution + ідемпотентність: чому вони працюють ТІЛЬКИ в парі.

  python r4_idempotency_durable.py unsafe   # resume -> ДРУГИЙ платіж на 50 000
  python r4_idempotency_durable.py safe     # той самий resume, платіж один

Сюжет: агент платить постачальнику. Вузол charge робить side effect (запис у
«банківський реєстр» ledger.json), потім процес падає. Чекпойнтер дає resume —
але вузол після resume стартує З ПОЧАТКУ, тому side effect виконається вдруге.
Рятує не чекпойнтер, а idempotency_key, згенерований ОДИН раз вище за течією.
"""
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

HERE = Path(__file__).parent
# Два сховища поруч — і вся суть демо у різниці між ними.
DB = HERE / "r4.db"                       # стан агента: чекпойнтер, LangGraph відкотить
BANK_LEDGER = HERE / "bank_ledger.json"   # стан БАНКУ: зовнішня система, ніхто не відкотить
# Анотація обов'язкова: RunnableConfig — це TypedDict, і без неї літерал
# виводиться як звичайний dict, який до нього не приводиться.
CONFIG: RunnableConfig = {"configurable": {"thread_id": "payment-17"}}
MODE = (sys.argv[1:] or ["unsafe"])[0]           # unsafe | safe


# --- «банк»: реальне сховище операцій ----------------------------------------

def bank_transfer(amount: int, vendor: str, idempotency_key: str | None) -> dict:
    """Реєстр банку — НЕ частина стану графа. Записане тут падіння переживає."""
    payments = json.loads(BANK_LEDGER.read_text()) if BANK_LEDGER.exists() else []

    # Check: чи виконувалася вже ця ЛОГІЧНА операція?
    if idempotency_key:
        for existing in payments:
            if existing["idempotency_key"] == idempotency_key:
                print(f"  [банк] ключ {idempotency_key[:8]} вже виконано -> already_exists, "
                      f"без нового переказу")
                return {"status": "already_exists", "payment_id": existing["payment_id"]}

    payment = {"payment_id": f"pay-{len(payments) + 1}", "amount": amount, "vendor": vendor,
               "idempotency_key": idempotency_key}
    payments.append(payment)                      # Act: сам side effect
    BANK_LEDGER.write_text(json.dumps(payments, ensure_ascii=False, indent=2))
    print(f"  [банк] СПИСАНО {amount} UAH -> {payment['payment_id']}")
    return {"status": "created", "payment_id": payment["payment_id"]}


# --- граф: prepare -> charge -> report ---------------------------------------

class State(TypedDict, total=False):
    amount: int
    vendor: str
    idempotency_key: str
    payment_id: str
    crash: bool


def prepare(state: State) -> dict:
    print("[node] prepare: збираємо реквізити")
    # Ключ генерується ОДИН раз на рівні оркестратора, а не всередині tool.
    # Він частина стану -> переживає падіння разом із чекпойнтом.
    key = str(uuid.uuid4()) if MODE == "safe" else None
    if key:
        print(f"  [prepare] idempotency_key = {key[:8]}… (лежить у state, тому переживе resume)")
    return {"amount": 50_000, "vendor": "ТОВ «Постачальник Плюс»", "idempotency_key": key}


def charge(state: State) -> dict:
    print("[node] charge: СТАРТ (після resume вузол виконується з початку!)")
    result = bank_transfer(state["amount"], state["vendor"], state.get("idempotency_key"))
    if state.get("crash"):
        raise ConnectionError("процес упав одразу після переказу, до коміту стану")
    return {"payment_id": result["payment_id"]}


def report(state: State) -> dict:
    print(f"[node] report: платіж {state['payment_id']} проведено")
    return {}


def build():
    g = StateGraph(State)
    g.add_node("prepare", prepare)
    g.add_node("charge", charge)
    g.add_node("report", report)
    g.set_entry_point("prepare")
    g.add_edge("prepare", "charge")
    g.add_edge("charge", "report")
    g.add_edge("report", END)
    conn = sqlite3.connect(str(DB), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


DB.unlink(missing_ok=True)
BANK_LEDGER.unlink(missing_ok=True)
graph = build()

print(f"=== режим {MODE}: {'з idempotency_key' if MODE == 'safe' else 'БЕЗ idempotency_key'} ===\n")
print("--- перший запуск, падіння всередині charge ---")
try:
    graph.invoke({"crash": True}, CONFIG)
except ConnectionError as e:
    print(f"[error] {e}")

snap = graph.get_state(CONFIG)
print(f"[state] .next = {snap.next}  <-- superstep не закомічено, charge треба переграти")

print("\n--- resume у новому процесі: чинимо причину падіння і продовжуємо ---")
graph.update_state(CONFIG, {"crash": False})
graph.invoke(None, CONFIG)                        # None = «продовжи звідти, де стояв»

payments = json.loads(BANK_LEDGER.read_text())
print(f"\n[банк] записів у реєстрі: {len(payments)}")
for payment in payments:
    print("   ", {k: (v[:8] + "…" if k == "idempotency_key" and v else v)
                  for k, v in payment.items()})
print(f"[банк] списано всього: {sum(p['amount'] for p in payments)} UAH")
print("[висновок] " + ("подвійний платіж: durable execution переграв side effect"
                       if len(payments) > 1 else
                       "платіж один: replay спіймав ключ і не створив дубль"))
