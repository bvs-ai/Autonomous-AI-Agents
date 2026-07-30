"""Pydantic v2 замість рукописного валідатора з 001: та сама пара інструментів,
але контракт тепер живе в ОДНІЙ моделі -- вона одночасно:
  1. схема (model_json_schema() -- те, що піде провайдеру як parameters);
  2. runtime-валідатор (model_validate(dict) -- сире -> типізований об'єкт або ValidationError);
  3. документація (Field(description=...) -- те, що читає модель).

model_config = ConfigDict(extra="forbid") -- Pydantic за замовчуванням extra="ignore",
для інструментів це треба свідомо змінювати: інакше зайве поле від моделі тихо
проковтнеться, а не спрацює як Schema Mismatch.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class QueryOrdersInput(BaseModel):
    """Отримати список замовлень із заданим статусом."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["повернення", "доставлено"] = Field(description="Статус замовлення")


class CheckReturnPolicyInput(BaseModel):
    """Перевірити, чи можна ще повернути замовлення."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^A-\d{4}$", description="Ідентифікатор замовлення, напр. 'A-1001'")

    @field_validator("order_id", mode="before")
    @classmethod
    def normalize(cls, v: str) -> str:
        # mode="before": нормалізація має відбутися ДО вбудованої перевірки pattern,
        # інакше "a-1001" впаде на pattern раніше, ніж дійде до цього валідатора.
        
        # Тут могла бути справжня валідація, наприклад така:
        #if not isinstance(v, str):
        #  raise ValueError("order_id має бути рядком")
        
        # Але головна функція цього валідатора - підготовка та приведення даних
        return v.strip().upper() if isinstance(v, str) else v


if __name__ == "__main__":
    print("[JSON_SCHEMA] QueryOrdersInput")
    print(json.dumps(QueryOrdersInput.model_json_schema(), ensure_ascii=False, indent=2))
    print()

    raw_calls = [
        (QueryOrdersInput, {"status": "повернення"}),
        (QueryOrdersInput, {"status": "скасовано"}),
        (QueryOrdersInput, {"status": "повернення", "priority": "high"}),
        (CheckReturnPolicyInput, {"order_id": "a-1001"}),  # нормалізується у "A-1001"
        (CheckReturnPolicyInput, {"order_id": "1001"}),
    ]

    for model, payload in raw_calls:
        try:
            parsed = model.model_validate(payload)
            print(f"[OK] {model.__name__}({payload}) -> {parsed!r}")
        except ValidationError as error:
            print(f"[REJECTED] {model.__name__}({payload}) -> {error.error_count()} помилка(ок):")
            for e in error.errors():
                print(f"    {'.'.join(str(p) for p in e['loc'])}: {e['msg']}")
