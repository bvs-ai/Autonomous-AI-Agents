"""Проміжний крок між Pydantic (002) і реальним викликом провайдера (006):
model_json_schema() -- ще НЕ strict-схема.

extra="forbid" дає additionalProperties:false, і на цьому інтуїція зазвичай
зупиняється. Але strict-режим OpenAI має ще дві вимоги, про які легко забути:

  1. усі властивості мають бути в required -- «необов'язкових» полів у strict
     немає; опціональність виражається типом, що допускає null
     (у Pydantic для `str | None` це вже готовий anyOf з {"type": "null"});
  2. default у схемі не допускається.

Тому між Pydantic-моделлю і полем parameters має стояти маленький адаптер.
Мережа не потрібна -- дивимося лише на схеми.

Запуск:  python 005_pydantic_to_strict_schema.py
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QueryOrdersInput(BaseModel):
    """Той самий контракт, що й у 002, але з опціональним полем since."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["повернення", "доставлено"] = Field(description="Статус замовлення")
    since: str | None = Field(default=None, description="Нижня межа дати доставки, YYYY-MM-DD")


def to_strict(model: type[BaseModel]) -> dict:
    """Адаптер Pydantic -> parameters для strict-режиму."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)

    for prop in schema["properties"].values():
        prop.pop("default", None)  # strict не приймає default
        prop.pop("title", None)  # шум, що лише витрачає токени

    schema["required"] = list(schema["properties"])  # усі поля обов'язкові
    return schema


if __name__ == "__main__":
    raw = QueryOrdersInput.model_json_schema()
    strict = to_strict(QueryOrdersInput)

    print("[AS_IS] опис поля since у Pydantic:")
    print(f"    {json.dumps(raw['properties']['since'], ensure_ascii=False)}")
    print("    anyOf з null -- це вже і є «опціональність через тип», якої вимагає strict\n")

    print(f"[AS_IS]  required: {raw['required']}")
    print(f"[STRICT] required: {strict['required']}   <-- since тепер обов'язкове, але може бути null\n")

    print("[STRICT_PARAMETERS] те, що піде в поле parameters інструмента:")
    print(json.dumps(strict, ensure_ascii=False, indent=2))
