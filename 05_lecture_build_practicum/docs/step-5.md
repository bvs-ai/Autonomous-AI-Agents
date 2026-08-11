# Крок 5 — захисні механізми

`step5_guards.py`, 158 рядків. Топологія графа та сама, що в кроці 3
(`agent ⇄ tools`). Змінилися стан і вміст вузла агента.

## Проблема

У кроці 3 з'ясувалось: цикл агента закінчується тоді, коли модель поверне
відповідь без `tool_calls`. Тобто **умову виходу з циклу контролює модель**.
Якщо вона не зупиниться — не зупиниться ніхто.

Три різні способи «не зупинитись» — три різні захисти:

| Захист | Від чого |
|---|---|
| `MAX_STEPS = 10` | агент працює, але нескінченно довго |
| `TIMEOUT_SEC = 120` | окремий крок завис (зовнішній сервіс не відповідає) |
| детекція повторів | агент зациклився на одній і тій самій дії |

## Розширений стан

```python
class GuardedState(TypedDict):
    messages: Annotated[list, add_messages]
    step_count: int
    start_time: float
    trajectory: list       # JSON-траєкторія
    last_tool_calls: list  # для детекції повторів
```

Тут уперше пишеться власний стан замість готового `MessagesState`. Гарний
привід закріпити редьюсери:

- `messages` має анотацію `add_messages` → нові повідомлення **дописуються**;
- решта полів анотації не мають → **перезапис**.

Чому так: `messages` пишуть обидва вузли (`agent` і `tools`), дані мають
накопичуватись. `step_count` пише лише `agent`, і йому потрібна саме заміна.

Через перезапис траєкторію доводиться оновлювати вручну:

```python
traj = state.get("trajectory", [])
traj.append({...})
return {..., "trajectory": traj}
```

## Порядок перевірок — спочатку дешеве, потім дороге

```python
def guarded_agent_node(state: GuardedState) -> dict:
    step = state.get("step_count", 0) + 1
    start = state.get("start_time") or time.time()
    elapsed = time.time() - start

    if step > MAX_STEPS:          # перевірка 1 — до виклику моделі
        return {...}
    if elapsed > TIMEOUT_SEC:     # перевірка 2 — теж до
        return {...}

    response = llm_with_tools.invoke(messages)      # дорогий виклик

    if current_calls and current_calls == prev_calls:   # перевірка 3 — після
        return {...}
```

Перші дві — **до** звернення до моделі: якщо ліміт вичерпано, платити за
запит немає сенсу. Третя вимушено **після**: щоб зрозуміти, що модель
повторюється, треба побачити її чергову відповідь.

## Захист не кидає виняток

```python
if step > MAX_STEPS:
    logger.warning(f"Досягнуто ліміт кроків ({MAX_STEPS})")
    return {
        "messages": [AIMessage(content=f"⚠️ Досягнуто ліміт у {MAX_STEPS} кроків. "
                                       f"Надаю найкращу відповідь на основі зібраних даних.")],
        "step_count": step,
    }
```

Повертається звичайне `AIMessage` **без `tool_calls`**. Далі спрацьовує
`tools_condition` на ребрі: викликів немає → перехід у `END`. Граф
завершується штатно.

Тобто зупинка виглядає як нормальна відповідь агента, тільки з поміткою.
Користувач отримує «я не встиг, ось що є», а не аварію. Історія діалогу при
цьому лишається валідною.

## Час старту має пережити ітерації

```python
start = state.get("start_time") or time.time()
...
return {..., "start_time": start}
```

У конспекті на цьому місці був баг: час старту переставлявся на кожному
кроці, і таймаут не міг спрацювати взагалі ніколи.

Зверніть увагу, наскільки це непомітно: усе працює, помилок немає, просто
один із захистів мертвий. **Баг у захисному механізмі не видно на щасливому
шляху** — його видно лише тоді, коли захист мав спрацювати й не спрацював.

## Детекція повторів

```python
current_calls = []
if response.tool_calls:
    current_calls = [(tc["name"], json.dumps(tc["args"], sort_keys=True))
                     for tc in response.tool_calls]
prev_calls = state.get("last_tool_calls", [])
if current_calls and current_calls == prev_calls:
    return {"messages": [AIMessage(content="⚠️ Виявлено повторення дій. Завершую цикл.")], ...}
```

Відбиток виклику — пара `(ім'я, аргументи)`. **`sort_keys=True` обов'язковий**:
`{"a":1,"b":2}` і `{"b":2,"a":1}` — це той самий виклик, але різні рядки. Без
сортування порівняння не спрацює.

Обмеження реалізації, про які варто знати:
- ловиться лише **сусіднє** повторення; цикл A→B→A→B не спіймається;
- порівняння точне, «майже такий самий» запит пройде.

Чому не зробили жорсткіше (наприклад, множина всіх викликів за сесію)? Бо
законне повторення існує: опитати статус, повторити після помилки. Надто
сувора детекція ламає нормальні сценарії. Це компроміс.

## Головний прийом кроку: демо, яке спрацьовує завжди

```python
def fresh_state(query: str, **overrides) -> dict:
    state = {
        "messages": [HumanMessage(content=query)],
        "step_count": 0,
        "start_time": time.time(),
        "trajectory": [],
        "last_tool_calls": [],
    }
    state.update(overrides)
    return state
```

```python
# ліміт кроків
guarded_agent.invoke(fresh_state("Хто такий Тарас Шевченко?", step_count=MAX_STEPS))

# таймаут
guarded_agent.invoke(fresh_state("Хто такий Тарас Шевченко?",
                                 start_time=time.time() - TIMEOUT_SEC - 1))

# повтори
already = [("calculator", json.dumps({"expression": "2+2"}, sort_keys=True))]
guarded_agent.invoke(fresh_state("Порахуй 2+2", last_tool_calls=already))
```

Замість того щоб чекати, доки агент випадково зациклиться (може не статись
ніколи), ми **стартуємо граф зі стану, в якому захист зобов'язаний
спрацювати**: лічильник уже на межі, час старту в минулому, «попередній
виклик» уже записаний.

Це можливо тільки тому, що стан графа — звичайний словник, який передається
ззовні. І звідси корисний висновок:

> Якщо захист неможливо перевірити інакше, ніж «у бою» — його спроектовано
> погано.

Усі три перевірки читають виключно поля стану, тому їх видно підстановкою.
Якби `step_count` жив у глобальній змінній, ні продемонструвати, ні
протестувати це було б неможливо.

## Чого тут немає

- **Ліміту на токени / вартість.** Природний четвертий захист: рахувати
  `usage_metadata` і зупинятись за бюджетом.
- **Власного ліміту LangGraph.** У `invoke` є
  `config={"recursion_limit": N}` (за замовчуванням 25) — рушій сам обірве
  граф, але **винятком** `GraphRecursionError`, а не м'якою відповіддю.
  Це останній рубіж, а не заміна власним захистам.

## Перевірити

```bash
.venv/bin/python step5_guards.py
```

Спробуйте змінити ліміт і подивитись, як зміниться поведінка:

```bash
.venv/bin/python -c "
import step5_guards as g
g.MAX_STEPS = 1
r = g.guarded_agent.invoke(g.fresh_state('Хто такий Тарас Шевченко?'))
print(r['messages'][-1].content)
print('кроків:', r['step_count'])
"
```

І подивитись на траєкторію, що живе прямо в стані графа:

```bash
.venv/bin/python -c "
import json
from step5_guards import guarded_agent, fresh_state
r = guarded_agent.invoke(fresh_state('Порахуй 12*12 і скажи дату'))
print(json.dumps(r['trajectory'], ensure_ascii=False, indent=2))
"
```

Останній експеримент: подивіться, що зробить вбудований `recursion_limit`:

```bash
.venv/bin/python -c "
from step3_react import react_agent
try:
    react_agent.invoke({'messages':[{'role':'user','content':'Привіт'}]}, config={'recursion_limit': 1})
except Exception as e:
    print(type(e).__name__, e)
"
```
