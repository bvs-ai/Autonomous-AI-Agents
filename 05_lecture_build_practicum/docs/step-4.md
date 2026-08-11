# Крок 4 — structured outputs і лог траєкторії

`step4_structured.py`, 111 рядків. Дві теми в одному файлі, і обидві про те,
як зробити роботу агента придатною для машинної обробки: на вході в код
(типізована відповідь) і на виході в логи (структурований запис).

## Частина 1. Як змусити модель повернути об'єкт

```python
class PlanStep(BaseModel):
    step_id: int = Field(..., description="Номер кроку (починаючи з 1)")
    description: str = Field(..., description="Опис дії", max_length=500)
    tool_name: Optional[str] = Field(None, description="Назва інструмента, якщо потрібен")

class Plan(BaseModel):
    goal: str = Field(..., description="Мета задачі")
    steps: list[PlanStep] = Field(..., description="Список кроків", min_length=1, max_length=15)
    reasoning: str = Field(..., description="Обґрунтування плану")
```

Це той самий Pydantic, що в кроці 2, але розвернутий в інший бік: там схема
описувала **вхід** інструмента, тут — **вихід** моделі. Один механізм, два
застосування.

```python
structured_llm = llm.with_structured_output(Plan, method="json_schema")
test_plan = structured_llm.invoke(
    "Склади план, щоб дізнатися населення п'яти найбільших міст України"
)

print(test_plan.goal)                    # рядок
print(test_plan.steps[0].description)    # вкладений об'єкт
```

`test_plan` — **екземпляр `Plan`**, не текст. Ніякого розбору відповіді
регулярками.

### Чому `method="json_schema"`

Способів отримати структуровану відповідь щонайменше три:

| Метод | Як працює | Коли доречний |
|---|---|---|
| `json_mode` | модель просто перемикають у режим «відповідай JSON-ом» | схема моделі не передається; на частині моделей Gemini повертає `None` |
| `function_calling` | схема подається як опис функції, відповідь — «виклик» цієї функції | універсальний запасний варіант для старих моделей |
| `json_schema` | схема передається провайдеру як нативний constrained decoding | актуальні Gemini/OpenAI; відповідь валідна за побудовою |

У демо стоїть `json_schema`: сучасні моделі Gemini підтримують його нативно —
провайдер сам обмежує генерацію так, щоб вихід відповідав схемі. Для старіших
моделей (і саме тому в коді залишено коментар) робочим варіантом був
`function_calling`: structured output там реалізовано **тим самим механізмом**,
що й інструменти в кроці 3 — модель «викликає функцію `Plan`», а бібліотека
розбирає аргументи виклику в об'єкт.

Це ще один прояв того, про що йшлося в кроці 1: інтерфейс однаковий
(`with_structured_output`), а те, який `method` реально працює, залежить від
провайдера й навіть від версії моделі.

> Побачите `None` замість об'єкта — не поспішайте лагодити промпт. Спершу
> спробуйте інший `method`.

### Дві деталі схеми, які варто помітити

**`Optional[str] = None` у `tool_name`.** Крок «скласти остаточний список»
інструмента не потребує. Якби поле було обов'язковим, модель вигадала б
неіснуючу назву інструмента, аби лише заповнити схему.

> Схема має дозволяти чесне «не застосовується» — інакше вона провокує
> вигадування.

**`min_length=1` у `steps`.** Порожній план невалідний. Обмеження потрапляє в
схему, тобто модель знає про нього **до** генерації, і Pydantic перевіряє
**після**. Подвійна страховка.

**`reasoning`** — поле для пояснення. Дає моделі місце «подумати вголос»
всередині структури й дає людині зрозуміти, чому план такий.

## Частина 2. Логер траєкторії

Звичайний клас, без магії фреймворку:

```python
def log_step(self, step_num: int, node: str, input_summary: str,
             output_summary: str, duration_sec: float,
             tool_name: Optional[str] = None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": step_num,
        "node": node,
        "tool": tool_name,
        "input": input_summary[:500],
        "output": output_summary[:500],
        "duration_sec": round(duration_sec, 3),
    }
    self.entries.append(entry)
    logger.info(f"Step {step_num} | {node} | {duration_sec:.2f}s | tool={tool_name}")
```

- **Запис — словник з фіксованими ключами**, а не рядок. Такий лог можна
  агрегувати й рахувати по ньому статистику; `f"Крок {n} виконано"` — не можна.
- **Час у UTC та в ISO 8601.** Демо, а часові пояси зроблено правильно.
- **Обрізка `[:500]`** — з тієї ж причини, що в кроці 2: вміст повідомлень
  буває величезним, а лог, який неможливо відкрити, марний.
- **Два виводи одразу**: у пам'ять (потім у JSON-файл) і в `logger` для
  людини.

```python
def summary(self) -> dict:
    return {
        "total_steps": len(self.entries),
        "total_time_sec": round(total_time, 3),
        "tools_used": tools_used,          # з повторами — видно зациклення
        "unique_tools": list(set(tools_used)),  # без — видно покриття
    }
```

Це зародок метрик агента: скільки кроків, скільки часу, якими інструментами.

## Чесне обмеження цього логера

```python
result = react_agent.invoke({"messages": [HumanMessage(content="...")]})
total = time.time() - t0

for m in result["messages"]:
    ...
    tl.log_step(step, "agent", "", str(m.content), total / len(result["messages"]), ...)
```

Лог будується **після** завершення, розбором фінальної історії. Тому час на
крок несправжній: загальна тривалість поділена нарівно між повідомленнями.
Реальної тривалості кроку так не отримати.

Три коректні способи:

1. **Заміряти всередині вузла** — так зроблено в кроці 5, там `t0`/`duration`
   міряються навколо конкретного виклику моделі.
2. **Стрімінг**: `for chunk in agent.stream(..., stream_mode="updates")` дає
   події в міру виконання, і час міряється за фактом. Плюс видно, як граф іде
   по вузлах.
3. **Callback-хуки** — так зроблено в `step4b_trajectory_hooks.py` (див. нижче).

## Крок 4b — той самий лог, але з чесним часом

`step4b_trajectory_hooks.py`, 117 рядків. Файл не переписує ні граф, ні вузли,
ні інструменти: він лише **спостерігає збоку**.

```python
class TrajectoryCallbackHandler(BaseCallbackHandler):
    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.started_at[run_id] = time.time()

    def on_llm_end(self, response, *, run_id, **kwargs):
        ...
        self._log(run_id, "agent", text)

react_agent.invoke(
    {"messages": [HumanMessage(content=query)]},
    config={"callbacks": [TrajectoryCallbackHandler(tl)]},
)
```

Ідея: LangChain **сам** викликає ці методи на початку й у кінці кожної
операції. Чотири хуки, зібрані у дві однакові пари:

| Старт | Фініш | Що міряємо |
|---|---|---|
| `on_chat_model_start` | `on_llm_end` | виклик моделі (вузол `agent`) |
| `on_tool_start` | `on_tool_end` | виклик інструмента (вузол `tools`) |

У `*_start` запам'ятовуємо час, у `*_end` віднімаємо — час виходить справжній,
а не поділений порівну.

**`run_id` — ключ, який усе тримає.** Це ідентифікатор конкретної операції,
однаковий у пари start/end. Без нього паралельні виклики інструментів
переплутали б свої заміри. Тому час зберігається як `dict[run_id] → t0`, а не
в одну змінну.

**Підключення — один рядок у `config`.** Ні граф, ні вузли, ні інструменти не
змінюються. Це головна перевага хуків над ручним логуванням: спостереження
відокремлене від логіки.

**Чого хуки не ловлять у цьому файлі.** Якщо операція впаде з винятком,
замість `*_end` спрацює `*_error` — такого кроку в журналі не буде. Хуків у
LangChain більше (`on_chain_*`, `on_retriever_*`, `on_retry`, помилки), тут
узято мінімум для однієї задачі.

Наприкінці файл друкує суму кроків і час усього запуску: сума трохи менша —
різниця це робота самого графа між викликами.

## Перевірити

```bash
.venv/bin/python step4_structured.py
cat trajectory.json
```

Тепер те саме з чесним часом — і порівняти два файли:

```bash
.venv/bin/python step4b_trajectory_hooks.py
diff <(jq '[.[].duration_sec]' trajectory.json) \
     <(jq '[.[].duration_sec]' trajectory_hooks.json)
```

У `trajectory.json` усі тривалості однакові (загальний час, поділений
порівну), у `trajectory_hooks.json` — різні й правдиві.

Подивитись, що структурований вихід — справді об'єкт:

```bash
.venv/bin/python -c "
from step1_setup import llm
from step4_structured import Plan
s = llm.with_structured_output(Plan, method='json_schema')
p = s.invoke('Склади план: дізнатися погоду в Києві та порівняти зі Львовом')
print(type(p))
print(p.goal)
for st in p.steps: print(' ', st.step_id, st.description, '| tool:', st.tool_name)
"
```

Побачити граф у русі (той самий агент, але зі стрімінгом):

```bash
.venv/bin/python -c "
from step3_react import react_agent
for chunk in react_agent.stream({'messages': [{'role':'user','content':'Порахуй 5^4 і скажи дату'}]}, stream_mode='updates'):
    print(list(chunk.keys()))
"
```
