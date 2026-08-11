# Крок 2 — інструменти й перевірка входу

`step2_tools.py`, 212 рядків. П'ять інструментів, і кожен складається з трьох
частин: **схема входу**, **опис для моделі**, **реалізація**.

## Інструмент = схема + опис + функція

```python
class CalcInput(BaseModel):
    expression: str = Field(..., description="Математичний вираз (числа, +, -, *, /, дужки, степені)",
                            min_length=1, max_length=200)

@tool(args_schema=CalcInput)
def calculator(expression: str) -> str:
    """Обчислює математичний вираз. Використовуй для арифметики, дужок, степенів."""
    ...
```

Дві речі тут працюють не так, як здається:

**`description` у `Field` — це не коментар.** Він потрапляє в опис функції,
який відправляється моделі разом із запитом. Від формулювання залежить, з
якими аргументами модель викличе інструмент.

**Docstring функції — теж частина промпту.** Модель читає саме його, щоб
вирішити, чи потрібен цей інструмент. Тому в ньому написано «Використовуй
для арифметики», а не «Обчислює вираз через numexpr».

Тобто половина коду цього файлу — текст для моделі, а не для людини.

## Аргументи вигадала модель — отже, це недовірені дані

Найважливіша думка кроку. Користувач пише текст, модель на його основі
складає аргументи, ваш код їх виконує. Між користувачем і `open(path, "w")`
стоїть лише схема.

```python
@field_validator("expression")
@classmethod
def validate_expression(cls, v: str) -> str:
    allowed = set("0123456789+-*/().eE^ ,")
    if not all(ch in allowed for ch in v):
        raise ValueError(f"Неприпустимі символи у виразі: {v}")
    return v.strip()
```

Це **білий список** (дозволено тільки перелічене), а не чорний (заборонено
перелічене). Чорний список завжди неповний: ви не передбачите всі способи
записати небезпечну конструкцію. Білий — передбачає, бо перелічує дозволене.

Навіщо: `calculator` усередині викликає `numexpr.evaluate` — інтерпретатор
виразів. Без білого списку туди можна спробувати підсунути пітонівський код.

## Захист від виходу з робочої теки

```python
class FileWriteInput(BaseModel):
    path: str = Field(..., description="Шлях до файлу")
    content: str = Field(..., description="Вміст для запису", max_length=10000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if ".." in v or v.startswith("/"):
            raise ValueError("Шлях не повинен містити '..' або починатися з '/'")
        return v
```

Чесно: **цієї перевірки недостатньо**. Вона не бачить символьних посилань,
не нормалізує шлях, не покриває Windows-шляхи. Надійніший варіант:

```python
full = (BASE_DIR / v).resolve()
if not full.is_relative_to(BASE_DIR.resolve()):
    raise ValueError("вихід за межі робочої теки")
```

Подумайте, як обійти варіант із демо — це корисна вправа.

Так само `HttpInput` перевіряє лише префікс `http://`/`https://`, тож
`http://localhost:8080/admin` пройде. Інструмент із доступом у мережу —
найнебезпечніший з усіх, і схема його не рятує; тут потрібні обмеження на
рівні мережі або білий список доменів.

## Усі інструменти повертають рядок і ніколи не падають

```python
@tool(args_schema=HttpInput)
def http_get(url: str, timeout_sec: int = 10) -> str:
    try:
        ...
        return json.dumps({"status": "ok", "url": url, "code": resp.status, "body": data[:1500]})
    except Exception as e:
        return json.dumps({"status": "error", "url": url, "error": str(e)})
```

Три правила, спільні для всіх п'яти інструментів:

**Повертається рядок.** Результат потрапляє в діалог як `ToolMessage`, а
діалог — це текст. JSON обрано тому, що моделі добре його розбирають.

**Виняток назовні не летить.** Помилка повертається як
`{"status": "error"}`. Це не «проковтування» помилки: виняток убив би весь
граф, а повернена помилка **потрапляє моделі в контекст**, і вона може
відреагувати — спробувати інший інструмент, переформулювати запит, сказати
користувачеві. Помилка стає частиною діалогу.

**Поле `status` однакове скрізь**: `ok` / `error` / `not_found`. Чим
стабільніша форма відповіді, тим передбачуваніша поведінка моделі.

Ще одна дрібниця з наслідками: `resp.read(2000)` і обрізка `[:1500]`.
Відповідь інструмента цілком їде в наступний запит до моделі. Сторінка на
200 КБ або не влізе в контекстне вікно, або коштуватиме як увесь інший
діалог. **Обрізати результат інструмента — обов'язково.**

## Два набори інструментів

```python
all_tools  = [calculator, current_datetime, wikipedia_search, http_get, file_write]
safe_tools = [calculator, current_datetime, wikipedia_search, http_get]
```

Два рядки, на яких тримається половина курсу. `file_write` виділено окремо,
бо це **незворотна дія**. Кроки 3, 5, 8 працюють тільки з `safe_tools` — там
ще немає підтвердження оператора, тож ризиковому інструменту нема чого
робити. У кроці 9 цей поділ перетвориться на два різні вузли графа.

## Дві дрібниці, які коштували години налагодження

```python
result = ne.evaluate(expression.replace("^", "**"))
```

`numexpr` не розуміє `^` як степінь. Схема цей символ дозволяє, тож без
заміни інструмент падав би на цілком валідному вводі.

```python
wikipedia_lib.set_user_agent("AgentBot/1.0 (LangGraph course demo)")

wiki = WikipediaAPIWrapper(wiki_client=wikipedia_lib, lang=lang,
                           top_k_results=1, doc_content_chars_max=1000)
```

Без власного User-Agent Wikipedia періодично віддає порожнє тіло, і
бібліотека падає з `Expecting value: line 1 column 1`. Виглядає як «агент
зламався», а насправді — вимога зовнішнього API.

`wiki_client` передається явно, хоча без нього код теж працює: у схемі
`WikipediaAPIWrapper` це поле обов'язкове, і модуль підставляє `model_validator`
уже під час валідації. Статичний аналізатор (mypy, Pylance) цього не бачить і
підсвічує виклик як помилку. Дрібний, але типовий випадок: рантайм-магія
Pydantic коштує зламаної перевірки типів.

## Перевірити

Найголовніше в цьому кроці: **інструмент можна викликати без моделі**.

```bash
.venv/bin/python step2_tools.py
```

```bash
.venv/bin/python -c "
from step2_tools import calculator, current_datetime
print(calculator.invoke({'expression': '2^10 + 3^5'}))
print(current_datetime.invoke({'format': 'day'}))
"
```

Це звичайна функція: детермінована, її можна налагоджувати й покривати
тестами. Запам'ятайте прийом — більшість випадків «агент тупить» насправді є
«інструмент повертає сміття».

Тепер атака — і перевірка, що тіло функції **не виконалось**:

```bash
.venv/bin/python -c "
from step2_tools import calculator
from step2_tools import FileWriteInput
try:
    calculator.invoke({'expression': \"__import__('os').system('ls')\"})
except Exception as e:
    print('відбито:', type(e).__name__)
try:
    FileWriteInput(path='../etc/passwd', content='hack')
except Exception as e:
    print('відбито:', type(e).__name__)
"
```

І подивитись, що саме бачить модель:

```bash
.venv/bin/python -c "
from step2_tools import calculator
print(calculator.name)
print(calculator.description)
import json; print(json.dumps(calculator.args_schema.model_json_schema(), ensure_ascii=False, indent=2))
"
```

Останній вивід — це буквально те, що йде в запит до моделі разом із вашим
питанням.
