# Крок 1 — агент без пам'яті

Базовий агент: цикл «модель → інструменти → модель». Пам'яті ще немає, але
з'являється те, на чому вона триматиметься — **історія ходу** й **облік
токенів**.

## Єдиний вид пам'яті тут — список повідомлень

`agent.py`:

```python
class Agent:
    def __init__(self, on_tool=None):
        self.history: list[dict] = []
```

Це робоча пам'ять агента. Вона живе рівно стільки, скільки живе процес.

## Цикл ходу

```python
def run_turn(self, user_input: str) -> str:
    self.history.append({"role": "user", "content": user_input})

    for _ in range(MAX_ITERATIONS):
        messages = [{"role": "system", "content": self.system_prompt()}, *self.history]
        message = llm.chat(messages, tools.SCHEMAS)

        if not message.tool_calls:                    # модель відповіла
            answer = message.content or "(порожня відповідь)"
            self.history.append({"role": "assistant", "content": answer})
            return answer

        self.history.append(_assistant_message(message))   # модель попросила інструменти

        for c in message.tool_calls:
            result = tools.call(c.function.name, _parse_args(c.function.arguments))
            self.history.append(
                {"role": "tool", "tool_call_id": c.id, "content": result}
            )
```

Три речі, які тут неочевидні:

**Промпт збирається щоразу заново.** `system_prompt()` викликається на кожній
ітерації. Поки він статичний, це не має значення — але саме сюди в кроці 2
прийде пам'ять, і тоді питання «що саме там лежить і чи змінюється воно»
стане ключовим.

**Кожен виклик інструмента назавжди лишається в історії.** Прочитали файл на
400 рядків — ці 400 рядків будуть у промпті до кінця сесії. Звідси лінійне
зростання контексту, яке лікує крок 5.

**Усі `tool_calls` треба закрити.** Модель може попросити три інструменти
одразу; якщо повернути результат не на кожен, API поскаржиться на незакритий
виклик. Тому цикл `for c in message.tool_calls` обробляє всі.

## Помилка інструмента — це текст, а не виняток

`tools.py`:

```python
def call(name: str, args: dict) -> str:
    if name not in HANDLERS:
        return f"ПОМИЛКА: інструмента '{name}' не існує."
    try:
        result = str(HANDLERS[name](**args))
    except Exception as exc:
        return f"ПОМИЛКА в '{name}': {exc}"
```

Виняток обірвав би хід. Текст помилки натомість повертається моделі, і вона
виправляється сама — наприклад, бачить «шлях поза робочим каталогом» і
пробує інший шлях.

## Облік токенів

`llm.py` рахує кожен виклик:

```python
def add(self, u) -> None:
    self.calls += 1
    self.prompt += u.prompt_tokens
    self.prompt_history.append(u.prompt_tokens)
    self.cached += _cached_tokens(u)
```

`prompt_history` — це і є вимірювальний прилад лекції. Все подальше існує
заради того, щоб це число не росло безконтрольно.

`cached` рахує токени, що прийшли з prefix cache. Провайдери повідомляють про
них по-різному, тому читаються два поля:

```python
def _cached_tokens(u) -> int:
    flat = getattr(u, "prompt_cache_hit_tokens", None)
    if flat is not None:
        return flat
    details = getattr(u, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0
```

## Перевірити

```
› Які залежності у проєкті?
› Скільки файлів у devmate?
› /usage
```

У `/usage` подивіться на рядок «розмір промпту»: числа ростуть від ходу до
ходу. Тепер вийдіть і зайдіть знову — агент не пам'ятає нічого.
