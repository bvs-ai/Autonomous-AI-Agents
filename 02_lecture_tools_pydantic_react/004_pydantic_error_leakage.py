"""Помилка валідації -- це теж повідомлення МОДЕЛІ, а не тільки запис у лог.

Коли інструмент відхиляє аргументи (002), текст ValidationError повертається
агентом як Observation -- тобто потрапляє в контекст LLM, у логи провайдера і
в подальшу історію діалогу. А Pydantic за замовчуванням вкладає в текст помилки
сире значення поля: input_value='4111-1111-1111-1111'.

Два запобіжники:
  1. hide_input_in_errors=True -- Pydantic перестає показувати саме значення;
  2. власна redaction -- віддавати моделі лише loc+msg, а не str(error).

Запуск:  python 004_pydantic_error_leakage.py
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PaymentLookupInput(BaseModel):
    """Контракт інструмента, що приймає чутливі дані."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^A-\d{4}$")
    card_number: str = Field(pattern=r"^\d{16}$", description="Номер картки без пробілів")


class PaymentLookupInputSafe(PaymentLookupInput):
    """Той самий контракт -- але помилка більше не цитує значення поля."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def as_observation(error: ValidationError) -> list[dict]:
    """Redaction: моделі потрібні лише поле і причина, щоб виправитися.

    Це корисно навіть з hide_input_in_errors -- str(error) містить ще й url
    документації та службовий шум, який лише роздуває контекст.
    """
    return [{"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]} for e in error.errors()]


if __name__ == "__main__":
    payload = {"order_id": "A-1001", "card_number": "4111-1111-1111-1111"}

    for model in (PaymentLookupInput, PaymentLookupInputSafe):
        try:
            model.model_validate(payload)
        except ValidationError as error:
            detail = str(error).splitlines()[2].strip()
            print(f"[{model.__name__}]\n    {detail}\n")

    try:
        PaymentLookupInput.model_validate(payload)
    except ValidationError as error:
        print(f"[REDACTED_OBSERVATION] {as_observation(error)}")
