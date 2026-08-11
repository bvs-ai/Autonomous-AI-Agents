# Крок 6 — Plan-and-Execute

`step6_plan_execute.py`, 205 рядків. Найскладніший файл демо й найдовший на
прогоні: від 45 секунд до 2,5 хвилин. Наберіться терпіння.

## Навіщо, якщо є ReAct

ReAct з кроку 3 вирішує **покроково, без загального плану**: на кожній
ітерації модель бачить історію і обирає наступну дію. Для коротких задач це
добре, для багатокрокових — погано: агент губить мету, повторюється, не бачить
структури.

Plan-and-Execute розділяє «що робити» і «як робити»:

```
planner   → будує план цілком (один виклик моделі, structured output)
executor  → виконує ОДИН крок плану (вкладеним ReAct-агентом)
replanner → дивиться на результати і вирішує: continue / replan / finish
```

## Стан

```python
class PlanExecuteState(TypedDict):
    messages: Annotated[list, add_messages]
    task: str                    # вхідне завдання
    plan: list[str]              # поточний план — просто список описів
    completed_steps: list[str]   # результати виконаних кроків
    current_step_idx: int        # індекс поточного кроку
    response: str                # фінальна відповідь
    replan_count: int            # лічильник переплановувань
```

`response` працює як **прапорець завершення**: порожній рядок — працюємо,
непорожній — час виходити.

`replan_count` — той самий прийом, що `MAX_STEPS` у кроці 5, але для іншого
циклу. **У кожного циклу в системі має бути свій ліміт.**

## Planner

```python
structured_planner = llm.with_structured_output(Plan, method="json_schema")

plan_obj = None
for attempt in range(3):
    plan_obj = cast(Optional[Plan], structured_planner.invoke(
        f"Склади покроковий план для виконання задачі: {task}. "
        f"Кожен крок має бути конкретною дією, яку можна виконати за допомогою "
        f"інструментів: calculator, current_datetime, wikipedia_search, http_get. "
        f"Не більше 4 кроків."
    ))
    if plan_obj is not None and plan_obj.steps:
        break
    logger.warning(f"Planner: спроба {attempt+1}/3 — отримано порожню відповідь, повтор...")

if plan_obj is None or not plan_obj.steps:
    logger.error("Planner: не вдалося згенерувати план, використовуємо fallback")
    return {"plan": [task], "current_step_idx": 0, "completed_steps": [], "replan_count": 0}
```

Три рішення в одному блоці — плюс `cast(Optional[Plan], ...)` навколо `invoke`.
`with_structured_output` за сигнатурою повертає `dict | BaseModel`, тому
редактор не знає, що всередині саме `Plan`, і не підказує поля `.goal`/`.steps`.
`cast` у рантаймі не робить нічого, це підказка type checker'у. `Optional`
всередині касту не зайвий: Gemini справді іноді віддає `None` — власне заради
цього тут і стоїть цикл із трьох спроб.

**Промпт перелічує інструменти.** Планувальник до інструментів доступу не має,
він лише називає їх. Але якщо їх не перелічити — він напланує кроки, які
виконавець фізично не зможе зробити («відкрий пошту», «зателефонуй у банк»).

> План має будуватись у термінах реальних можливостей системи.

(Недолік реалізації: перелік зашитий у текст промпту, а не збирається з
`safe_tools`. Додасте інструмент — легко забути оновити промпт.)

**«Не більше 4 кроків»** — кожен крок це вкладений ReAct з кількома викликами
моделі. Обмеження глибини плану — теж захисний механізм.

**Ретрай + fallback навколо structured output.** Це вже **другий** рівень
надійності після `max_retries=6` у клієнті з кроку 1. Різниця важлива:

| Рівень | Що ловить |
|---|---|
| `max_retries` у `ChatGoogleGenerativeAI` | помилки передачі: 429, 5xx, таймаут |
| цикл `for attempt in range(3)` тут | **успішну** відповідь з порожнім вмістом |

HTTP 200, а об'єкта немає — для транспортного ретраю все чудово, він тут
безсилий. Це специфіка роботи з LLM: успіх на рівні протоколу ще не означає
придатний результат.

**Fallback `{"plan": [task]}`**: якщо план не збудувався, планом стає сама
задача одним кроком. Система деградує до звичайного ReAct, але не падає.

## Executor — тут викликається інший агент

```python
step_desc = plan[idx]
context = ""
if state["completed_steps"]:
    context = "\nПопередні результати:\n" + "\n".join(
        f"- Крок {i+1}: {r}" for i, r in enumerate(state["completed_steps"]))

prompt = (
    f"Виконай наступний крок: {step_desc}\n"
    f"Це крок {idx+1} з {len(plan)} загального плану.{context}\n"
    f"Використовуй інструменти за потребою. Поверни стислий результат."
)

result = react_agent.invoke({"messages": [HumanMessage(content=prompt)]})   # ← ось воно
step_result = get_text(result["messages"][-1].content)

return {"completed_steps": state["completed_steps"] + [step_result],
        "current_step_idx": idx + 1}
```

**Усередині вузла графа викликається цілий інший граф** — `react_agent` із
кроку 3. Один `pe_agent.invoke()` розгортається в N викликів
`react_agent.invoke()`, кожен зі своїм циклом «модель ⇄ інструменти». Звідси й
час прогону.

**Друга ключова ідея — керування контекстом.** Вкладений агент викликається з
**порожньою історією**: `{"messages": [HumanMessage(prompt)]}`. Він не бачить
ні попередніх кроків, ні початкової задачі — тільки те, що йому явно
переклали в текст промпту.

- **плюс:** контекст виконавця короткий і чистий, кожен крок коштує однаково
  незалежно від довжини плану;
- **мінус:** стиснення результатів у `context` губить деталі. Якщо крок 1
  знайшов три факти, а в підсумковий текст потрапив один — крок 3 решти не
  побачить.

> У багатоагентних системах питання не «як передати керування», а **що саме
> передати з контексту**. Передаси все — задихнешся в токенах; передаси мало —
> виконавець працює наосліп.

## Replanner

```python
class ReplanDecision(BaseModel):
    action: Literal["continue", "replan", "finish"] = Field(
        ..., description="continue=виконувати наступний крок, "
                         "replan=переплановувати, finish=завершити"
    )
    updated_plan: Optional[list[str]] = Field(
        None, description="Новий план (якщо action='replan')"
    )
    final_answer: Optional[str] = Field(
        None, description="Фінальна відповідь (якщо action='finish')"
    )
    reasoning: str = Field(..., description="Обґрунтування рішення")
```

**`Literal[...]`** замість вільного рядка: перелік дозволених дій потрапляє в
схему, модель не зможе повернути `"maybe"`. (Порівняйте з валідаторами мови в
кроці 2 — там те саме зроблено гірше, через `if v not in (...)`.)

**Умовно обов'язкові поля.** `updated_plan` потрібен лише при `replan`,
`final_answer` — лише при `finish`. Pydantic такої залежності декларативно не
виражає, тому вона винесена **в текст `description`** і продубльована в
промпті («обов'язково вкажи final_answer»), плюс підстрахована в коді:

```python
if decision.action == "finish":
    return {"response": decision.final_answer or "Завдання виконано."}
elif decision.action == "replan" and decision.updated_plan:
    ...
```

Тобто опис поля — теж частина контракту, а не документація.

Fallback тут цікавіший, ніж у планувальника:

```python
if decision is None:
    if remaining:
        return {}          # лишились кроки → просто продовжуємо
    return {"response": "Завдання виконано (replanner не відповів)."}
```

`return {}` — **порожня зміна, стан не змінюється**. Цілком легальне
повернення вузла: «мені нічого додати». Далі `should_continue` подивиться на
`current_step_idx` і вирішить сам. Тобто при відмові моделі керування
повертається звичайній логіці.

## Хто насправді ухвалює рішення

```python
def should_continue(state: PlanExecuteState) -> str:
    if state.get("response"):
        return "finish"
    if state.get("replan_count", 0) > 3:
        return "finish"        # захист від нескінченного переплановування
    if state["current_step_idx"] >= len(state["plan"]):
        return "finish"
    return "execute"
```

| Хто | Що вирішує | Природа |
|---|---|---|
| `replanner_node` | «задачу виконано? план треба міняти?» | модель, недетерміновано |
| `should_continue` | «в який вузол іти» | звичайний `if`, детерміновано |

Модель **висловлює судження**, код **ухвалює рішення про маршрут**. Причому
код має право переважити модель: `replan_count > 3` веде у `finish`, хай би що
модель хотіла.

> LLM в агенті — це порадник, а не диспетчер. Судження беремо в моделі,
> керування лишаємо коду.

## Граф

```python
pe_graph.add_edge(START, "planner")
pe_graph.add_edge("planner", "executor")
pe_graph.add_edge("executor", "replanner")
pe_graph.add_conditional_edges("replanner", should_continue,
                               {"execute": "executor", "finish": END})
```

```
START → planner → executor → replanner ──(finish)──> END
                     ^                │
                     └───(execute)────┘
```

Цикл тут **зовнішній**, між executor і replanner, і всередині нього
крутиться ще й внутрішній цикл ReAct. Два цикли — два незалежні ліміти.

`planner` викликається **рівно один раз**. Перепланування робиться не
поверненням у `planner`, а тим, що `replanner` кладе новий `plan` у стан і
скидає `current_step_idx = 0`.

## Перевірити

```bash
.venv/bin/python step6_plan_execute.py
```

У виводі шукайте: спершу друкується план по кроках, потім рядки
`Executor: крок N` (кожен — це повний запуск агента з кроку 3), потім рішення
replanner-а з обґрунтуванням.

Порівняйте два підходи на одній задачі:

```bash
.venv/bin/python -c "
import time
from step3_react import react_agent
from step6_plan_execute import pe_agent, new_pe_state
task = 'Дізнайся сьогоднішню дату і порахуй, скільки днів лишилось до Нового року'

t=time.time(); r=react_agent.invoke({'messages':[{'role':'user','content':task}]})
print('ReAct:', round(time.time()-t,1), 'с,', len(r['messages']), 'повідомлень')

t=time.time(); p=pe_agent.invoke(new_pe_state(task))
print('P&E:  ', round(time.time()-t,1), 'с,', len(p['completed_steps']), 'кроків плану')
"
```

Висновок, який ви побачите: Plan-and-Execute у рази дорожчий. Застосовувати
його треба там, де задача справді багатокрокова — або де план корисно
показати людині **до** виконання (це крок 9).
