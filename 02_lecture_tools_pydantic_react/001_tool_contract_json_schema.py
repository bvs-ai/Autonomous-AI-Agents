"""Інструмент як контракт: та сама пара query_orders / check_return_policy з лекції 1,
але тепер JSON Schema навмисно «закрита» — так, як має виглядати контракт у проді.

Порівняно з TOOLS у 006-012 лекції 1 (там schema була навчально-мінімальною) тут додано:
  - enum замість вільного рядка для status -> модель не може вигадати статус;
  - pattern для order_id -> формат перевіряється ще до виконання;
  - additionalProperties: false -> закрита схема, зайві поля= помилка, а не тихе ігнорування.

Друга половина файлу — рукописний валідатор (без бібліотек): показує, що саме
JSON Schema ловить ДО виконання інструмента, і мапує кожен провал на один із
п'яти типів помилок інструмента з конспекту лекції.
"""

import json

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Отримати список замовлень із заданим статусом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["повернення", "доставлено"],
                        "description": "Статус замовлення",
                    }
                },
                "required": ["status"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_policy",
            "description": "Перевірити, чи можна ще повернути замовлення.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "pattern": r"^A-\d{4}$",
                        "description": "Ідентифікатор замовлення, напр. 'A-1001'",
                    }
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
]


def validate_call(tool_name: str, args: dict) -> tuple[bool, str]:
    """Мінімальний рукописний валідатор виклику проти TOOLS.

    Повертає (ok, error_type). Не претендує на повноту jsonschema-рушія —
    лише показує, які саме перевірки «закриває» кожен рядок схеми.
    """
    schema = next((t["function"] for t in TOOLS if t["function"]["name"] == tool_name), None)
    if schema is None:
        return False, "Hallucinated Tool"

    params = schema["parameters"]
    for required_field in params["required"]:
        if required_field not in args:
            return False, "Schema Mismatch"

    if not params["additionalProperties"]:
        allowed = set(params["properties"])
        if set(args) - allowed:
            return False, "Schema Mismatch"

    for field, value in args.items():
        prop = params["properties"][field]
        if "enum" in prop and value not in prop["enum"]:
            return False, "Validation Error"
        if "pattern" in prop:
            import re

            if not re.fullmatch(prop["pattern"], str(value)):
                return False, "Validation Error"

    return True, ""


if __name__ == "__main__":
    print("[SCHEMA] query_orders\n" + json.dumps(TOOLS[0]["function"]["parameters"], ensure_ascii=False, indent=2))
    print()

    calls = [
        ("query_orders", {"status": "повернення"}),
        ("query_orders", {"status": "скасовано"}),  # Validation Error: немає в enum
        ("query_orders", {"status": "повернення", "priority": "high"}),  # Schema Mismatch: зайве поле
        ("check_return_policy", {"order_id": "A-1001"}),
        ("check_return_policy", {"order_id": "1001"}),  # Validation Error: не пройшов pattern
        ("check_return_policy", {}),  # Schema Mismatch: немає required order_id
        ("delete_order", {"order_id": "A-1001"}),  # Hallucinated Tool: такого інструмента немає
    ]

    for name, args in calls:
        ok, error_type = validate_call(name, args)
        status = "OK" if ok else f"REJECTED ({error_type})"
        print(f"[CALL] {name}({args}) -> {status}")
