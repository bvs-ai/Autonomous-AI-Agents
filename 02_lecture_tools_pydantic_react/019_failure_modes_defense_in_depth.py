"""Траєкторія "тижневий звіт по поверненнях", де збої йдуть один за одним --
рівно так, як описано в конспекті: галюцинація інструмента -> невірні аргументи ->
зациклювання на порожніх даних -> 503 від зовнішнього сервісу -> ризик переповнення
контексту. Без defense-in-depth агент впав би вже на кроці 1 з KeyError.

Тут агентний цикл СКРИПТОВАНИЙ (список запланованих "намірів моделі"), а не
викликає справжній LLM -- це навмисно: сценарій відтворюваний і детермінований,
а фокус лекції саме на тому, що ловить кожен шар захисту, а не на поведінці моделі.
У 011 лекції 1 ту саму ідею показував запуск `trap`, тільки там пастка була одна
(порожній результат) і модель мала на неї зреагувати сама. Тут пасток пʼять
і вони йдуть ланцюгом -- саме тому й потрібні ШАРИ, а не один запобіжник.

Три шари захисту (defense-in-depth):
  1. превентивний   -- closed Pydantic-схема, allowlist (перевірка ДО виконання);
  2. реактивний     -- retry+backoff на 503, loop detection, обрізання Observation;
  3. спостережуваний -- покроковий trace: у проді це рядки audit trail (010),
     що йдуть у structured logging (011).

Спершу виконується та сама траєкторія БЕЗ захисту -- щоб було видно, що агент
не «трохи гірше відповідає», а просто падає на першому ж кроці.
"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ALLOWED_TOOLS = {"query_orders", "check_return_policy"}
MAX_STEPS = 7
MAX_REPEATS = 3
MAX_OBSERVATION_CHARS = 200  # захист від Context Overflow: обрізаємо надто довгі Observation


class CheckReturnPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^A-\d{4}$")


ORDERS = {
    "A-1001": {"status": "повернення", "days_since_delivery": 3},
    "A-1002": {"status": "повернення", "days_since_delivery": 45},
}

# Запланована траєкторія "необережної" моделі -- один намір на крок:
PLANNED_INTENTS = [
    {"name": "generate_weekly_report", "args": {}},                      # 1: Hallucinated Tool
    {"name": "check_return_policy", "args": {"order_id": "1001"}},       # 2: невірні аргументи (Validation Error)
    {"name": "query_orders", "args": {"status": "скасовано"}},           # 3: порожній результат
    {"name": "query_orders", "args": {"status": "скасовано"}},           # 4: той самий виклик -- Looping
    {"name": "query_orders", "args": {"status": "скасовано"}},           # 5: той самий виклик втретє -> loop detection
    {"name": "check_return_policy", "args": {"order_id": "A-1001"}},     # 6: зовнішній сервіс віддає 503
    {"name": "check_return_policy", "args": {"order_id": "A-1002"}},     # 7: успіх, довге Observation
]


def call_external_service(order_id: str, attempt_state: dict) -> dict:
    """Симуляція нестабільного зовнішнього сервісу: перший виклик для A-1001 -- 503."""
    attempt_state[order_id] = attempt_state.get(order_id, 0) + 1
    if order_id == "A-1001" and attempt_state[order_id] == 1:
        raise ConnectionError("503 Service Unavailable")
    order = ORDERS[order_id]
    # Навмисно "занадто докладна" відповідь -- демонструє ризик Context Overflow.
    return {
        "order_id": order_id,
        "return_allowed": order["days_since_delivery"] <= 30,
        "raw_debug_dump": "x" * 500,  # у проді -- зайві діагностичні поля з внутрішнього API
    }


def query_orders(status: str) -> list[dict]:
    return [{"id": oid, **o} for oid, o in ORDERS.items() if o["status"] == status]


def run_trajectory() -> dict:
    trace = []
    seen_calls: list[str] = []
    attempt_state: dict = {}
    partial_results = []

    for step, intent in enumerate(PLANNED_INTENTS, start=1):
        if step > MAX_STEPS:
            trace.append({"step": step, "event": "STOPPED_BY_LIMIT", "reason": f"max_steps={MAX_STEPS}"})
            break

        name, args = intent["name"], intent["args"]
        signature = f"{name}:{args}"

        # --- Шар 1: превентивний -- allowlist ДО виконання ---
        if name not in ALLOWED_TOOLS:
            trace.append({"step": step, "event": "HALLUCINATED_TOOL_BLOCKED", "tool": name})
            continue

        # --- Шар 1: превентивний -- Pydantic-валідація ДО виконання ---
        if name == "check_return_policy":
            try:
                validated = CheckReturnPolicyInput.model_validate(args)
            except ValidationError as error:
                trace.append({"step": step, "event": "VALIDATION_ERROR_CAUGHT", "args": args, "error": str(error)})
                continue
            args = validated.model_dump()

        # --- Шар 2: реактивний -- loop detection ---
        seen_calls.append(signature)
        recent = seen_calls[-MAX_REPEATS:]
        if len(recent) == MAX_REPEATS and len(set(recent)) == 1:
            trace.append({"step": step, "event": "LOOP_DETECTED", "signature": signature})
            continue

        # --- Виконання інструмента (з реактивним retry на мережеву помилку) ---
        try:
            if name == "query_orders":
                result = query_orders(**args)
                if not result:
                    trace.append({"step": step, "event": "EMPTY_RESULT", "args": args})
                    continue
            else:
                try:
                    result = call_external_service(args["order_id"], attempt_state)
                except ConnectionError as error:
                    # Реактивний захист: одна автоматична повторна спроба.
                    trace.append({"step": step, "event": "EXTERNAL_ERROR_RETRYING", "error": str(error)})
                    result = call_external_service(args["order_id"], attempt_state)

            # --- Шар 2: обмеження розміру Observation (захист від Context Overflow) ---
            observation = str(result)
            if len(observation) > MAX_OBSERVATION_CHARS:
                observation = observation[:MAX_OBSERVATION_CHARS] + "...[truncated]"
                trace.append({"step": step, "event": "OBSERVATION_TRUNCATED", "original_len": len(str(result))})

            trace.append({"step": step, "event": "TOOL_CALL_RESULT", "tool": name, "observation": observation})
            if name == "check_return_policy":
                # У звіт кладемо лише корисні поля -- службовий дамп зовнішнього API
                # роздує контекст наступного кроку і нічого не додасть.
                partial_results.append({k: v for k, v in result.items() if k != "raw_debug_dump"})

        except Exception as error:  # noqa: BLE001 -- останній рубіж graceful degradation
            trace.append({"step": step, "event": "UNRECOVERABLE_ERROR", "error": str(error)})

    return {
        "trace": trace,
        "final_answer": {
            "note": "Частковий, але валідний звіт: збої на шляху не зупинили обробку.",
            "checked_orders": partial_results,
        },
    }


def run_naive() -> None:
    """Та сама траєкторія без жодного шару захисту -- як виглядає «просто цикл»."""
    tools = {"query_orders": query_orders, "check_return_policy": check_return_policy_raw}

    for step, intent in enumerate(PLANNED_INTENTS, start=1):
        print(f"[STEP {step}] {intent['name']}({intent['args']})")
        result = tools[intent["name"]](**intent["args"])  # ні allowlist, ні валідації
        print(f"          -> {result}")


def check_return_policy_raw(order_id: str) -> dict:
    return {"order_id": order_id, "return_allowed": ORDERS[order_id]["days_since_delivery"] <= 30}


if __name__ == "__main__":
    print("=== ВЕРСІЯ A: без захисту ===")
    try:
        run_naive()
    except Exception as error:
        print(f"          -> АГЕНТ УПАВ: {type(error).__name__}: {error}")
        print("          решта кроків не виконається -- користувач не отримає нічого\n")

    print("=== ВЕРСІЯ B: defense-in-depth ===")
    outcome = run_trajectory()
    for entry in outcome["trace"]:
        print(f"[STEP {entry['step']}] {entry['event']}: { {k: v for k, v in entry.items() if k not in ('step', 'event')} }")
    print(f"\n[FINAL_ANSWER] {outcome['final_answer']}")
