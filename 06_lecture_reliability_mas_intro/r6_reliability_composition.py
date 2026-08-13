"""r6 — композиція патернів надійності: тільки те, чого не видно на окремих з них.

  python r6_reliability_composition.py

Бюджет токенів і ідемпотентність сюди не входять — вони вже відіграні в r3 і r4,
а тут лише дублювали б код. Лишилося те, що видно ВИКЛЮЧНО в композиції:

  1. порядок: breaker ЗОВНІ, retry ВСЕРЕДИНІ (і чому не навпаки);
  2. таксономія розведена по рівнях: TransientError -> retry_policy,
     CircuitOpenError -> error_handler, а не один except на все;
  3. вузол зі side effect (pay) свідомо БЕЗ retry_policy;
  4. degraded їде через state і змінює РІШЕННЯ наступного вузла.

Конвеєр: lookup -> score -> pay. Мережі і LLM немає, вивід детермінований.
"""
import asyncio
from typing import TypedDict

from langgraph.errors import NodeError
from langgraph.graph import END, StateGraph
from langgraph.types import Command, RetryPolicy

from r5_circuit_breaker import CircuitBreaker, CircuitOpenError, TransientError

# Рівень ПРОЦЕСУ, а не state: сервіс лежить для всіх тредів одразу, тому
# лічильник збоїв спільний. У state він чекпойнтився б на thread_id.
BREAKER = CircuitBreaker(failure_threshold=3, cooldown=30.0)

CALLS: dict[str, int] = {}                 # спроби до реєстру, теж поза state
REGISTRY_SCRIPT = {"INV-1001": 2,          # скільки перших спроб віддадуть 503
                   "INV-1002": 0,          # реєстр здоровий
                   "INV-1003": 99}         # реєстр лежить завжди
RISK_MODEL_DOWN = {"INV-1002"}             # для кого впала основна risk-модель


class State(TypedDict, total=False):
    invoice: str
    vendor_status: str
    risk: float
    degraded: bool
    needs_human: bool
    status: str
    stop_reason: str


async def registry_lookup(invoice: str) -> str:
    """Детермінована заглушка: скільки перших спроб віддадуть 503 — у скрипті вище."""
    CALLS[invoice] = CALLS.get(invoice, 0) + 1
    await asyncio.sleep(0.05)
    if CALLS[invoice] <= REGISTRY_SCRIPT.get(invoice, 0):
        raise TransientError(f"registry: 503 (спроба {CALLS[invoice]})")
    return "active"


# --- вузли -------------------------------------------------------------------

async def lookup(state: State) -> dict:
    """Порядок має значення: breaker НАД викликом, retry — під ним.

    breaker.before() -> CircuitOpenError -> error_handler, виклику не буде.
    TransientError    -> retry_policy    -> LangGraph перезапускає вузол.
    Навпаки не працює: ретрай усередині breaker'а довбав би мертвий сервіс
    ще max_attempts разів на кожен виклик графа.
    """
    await BREAKER.before()
    try:
        status = await registry_lookup(state["invoice"])
    except TransientError:
        await BREAKER.on_failure()
        raise                                   # -> вирішує RetryPolicy
    await BREAKER.on_success()
    print(f"  [lookup]  контрагент {status}, спроб: {CALLS[state['invoice']]}")
    return {"vendor_status": status}


async def score(state: State) -> dict:
    """Fallback — ланцюг пріоритетів усередині вузла, а не «ще один retry».

    Запасне значення не має мовчки стати фактом: рівень довіри їде далі
    прапорцем degraded.
    """
    async def primary() -> dict:
        if state["invoice"] in RISK_MODEL_DOWN:
            raise TransientError("risk-model: 503")
        return {"risk": 0.07, "degraded": False}

    async def cheap() -> dict:
        return {"risk": 0.18, "degraded": True}

    for name, fn in (("основна модель", primary), ("резервна модель", cheap)):
        try:
            out = await fn()
        except TransientError as e:
            print(f"  [score]   рівень «{name}» впав: {e}")
            continue
        print(f"  [score]   ризик {out['risk']} від «{name}», degraded={out['degraded']}")
        return out
    return {"degraded": True, "needs_human": True}


async def pay(state: State) -> dict:
    """Side effect -> свідомо БЕЗ retry_policy. І рішення залежить від degraded."""
    if state.get("degraded"):
        print("  [pay]     ризик отримано з деградованого джерела -> на людину")
        return {"status": "escalated", "needs_human": True}
    print("  [pay]     платіж проведено автоматично")
    return {"status": "paid"}


async def degrade(state: State, error: NodeError) -> Command:
    """Збій вузла стає керованою деградацією, а не падінням графа."""
    kind = type(error.error).__name__
    print(f"  [degrade] вузол «{error.node}» -> {kind}: {error.error}")
    return Command(update={"status": "degraded", "needs_human": True, "degraded": True,
                           "stop_reason": f"{kind}: {error.error}"},
                   goto=END)


# --- складання: уся політика надійності видима в одному місці -----------------

g = StateGraph(State)
g.add_node(
    "lookup", lookup,
    # Таксономія — це аргумент retry_on. CircuitOpenError сюди НЕ входить:
    # повторювати відмову breaker'а безглуздо, вона й означає «не ходи».
    retry_policy=RetryPolicy(retry_on=TransientError, max_attempts=3,
                             initial_interval=0.1, max_interval=0.3, jitter=False),
    timeout=5.0,                                # дедлайн однієї спроби вузла
    error_handler=degrade,
)
g.add_node("score", score, error_handler=degrade)
g.add_node("pay", pay, error_handler=degrade)   # без retry_policy: є side effect
g.set_entry_point("lookup")
g.add_edge("lookup", "score")
g.add_edge("score", "pay")
g.add_edge("pay", END)

graph = g.compile()


async def run(title: str, invoice: str) -> None:
    print(f"\n[{title}] {invoice}")
    final = await graph.ainvoke({"invoice": invoice})
    print(f"  [підсумок] статус={final['status']}, "
          f"degraded={final.get('degraded', False)}, "
          f"needs_human={final.get('needs_human', False)}, "
          f"breaker={BREAKER.state.value}")
    if final.get("stop_reason"):
        print(f"  [підсумок] причина: {final['stop_reason']}")


async def main() -> None:
    await run("1. happy path: retry впорався, основна модель жива -> платимо", "INV-1001")
    await run("2. основна risk-модель впала: fallback -> degraded -> на людину", "INV-1002")
    await run("3. реєстр лежить: ретраї вичерпано, breaker відкрився", "INV-1003")
    print(f"\n[ціна] спроб до реєстру: {sum(CALLS.values())}")
    print(f"[breaker] стан {BREAKER.state.value}: наступний виклик буде fail-fast "
          f"без жодної спроби — це вже показано в r5")


asyncio.run(main())
