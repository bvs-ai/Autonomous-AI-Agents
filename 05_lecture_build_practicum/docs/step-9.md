# Крок 9 — Human-in-the-Loop

`step9_hitl.py`, 163 рядки. Тут сходяться інструменти (крок 2), граф (крок 3)
і checkpointer (крок 7). Без checkpointer цей крок фізично неможливий.

## Навіщо

Перевірка схеми з кроку 2 відповідає на питання «чи коректні аргументи». Вона
не відповідає на питання «**чи можна це взагалі робити**». Для незворотних
дій — запис у файл, переказ грошей, видалення, надсилання листа — потрібна
людина.

Механіка в LangGraph:

1. ризикові інструменти виносяться в **окремий вузол** графа;
2. граф компілюється з `interrupt_before=["risky_tools"]`;
3. виконання зупиняється **перед** вузлом, стан зберігається в чекпоінт;
4. людина дивиться на знімок стану й вирішує;
5. **approve** → `invoke(None, config)` продовжує з місця зупинки;
   **reject** → `update_state(..., as_node="risky_tools")` підставляє
   `ToolMessage` з відмовою замість виконання вузла, і далі той самий
   `invoke(None, config)`.

## Два вузли інструментів замість одного

```python
def is_risky_tool(state: MessagesState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            if tc["name"] == "file_write":
                return "risky"
        return "safe_tools"
    return END
```

```python
hitl_graph.add_node("agent", hitl_agent_node)
hitl_graph.add_node("safe_tools", ToolNode(safe_tools))
hitl_graph.add_node("risky_tools", ToolNode([file_write]))
hitl_graph.add_edge(START, "agent")
hitl_graph.add_conditional_edges("agent", is_risky_tool,
    {"safe_tools": "safe_tools", "risky": "risky_tools", END: END})
hitl_graph.add_edge("safe_tools", "agent")
hitl_graph.add_edge("risky_tools", "agent")
```

```
                 ┌──> safe_tools ──┐
START → agent ───┤                 ├──> agent → ... → END
                 └──> risky_tools ─┘
                      ▲
                 interrupt_before
```

**Чому два вузли, а не перевірка всередині одного:** `interrupt_before`
працює на рівні **вузла графа**, а не окремого виклику. Щоб пауза була
можлива, ризикова дія має бути окремою вершиною.

Також зверніть увагу: `tools_condition` із кроку 3 більше не годиться — він
розрізняє лише «є виклики / немає». Тут потрібні три варіанти, тому предикат
написаний вручну. Мітка `"risky"` не збігається з іменем вузла
`"risky_tools"` — зайве підтвердження, що функція повертає **мітку**, а
таблиця вже вирішує, куди вона веде.

**Слабке місце реалізації:** ім'я `"file_write"` зашите в предикат. Правильніше
було б `RISKY = {"file_write", ...}` або позначка в самому інструменті — інакше
новий небезпечний інструмент мовчки поїде в `safe_tools`. Спробуйте додати
`http_post` і подивіться, що доведеться змінити.

## Компіляція з перериванням

```python
with SqliteSaver.from_conn_string("hitl_checkpoints.db") as checkpointer:
    hitl_agent = hitl_graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["risky_tools"]
    )
```

**Чому HITL вимагає checkpointer** — питання, яке ставлять завжди. Пауза
означає, що між «зупинились» і «людина вирішила» минає час: можливо, години,
можливо — з перезапуском процесу. Стан має десь лежати. Чекпоінт і є це
«десь».

`interrupt_before` приймає список **імен вузлів**. Є і симетричний
`interrupt_after` — зупинитись *після* вузла.

## Точка зупинки

```python
hitl_agent.invoke({"messages": [HumanMessage(content="Запиши у файл report.txt ...")]},
                  config=config)

snapshot = hitl_agent.get_state(config)
print(f"   Наступний вузол: {snapshot.next}")

pending = snapshot.values["messages"][-1]
for tc in pending.tool_calls:
    print(f"   🔧 Інструмент: {tc['name']}")
    print(f"   📝 Аргументи: {json.dumps(tc['args'], ensure_ascii=False)}")
```

`invoke` **повертається штатно, без винятку** — але граф не завершено. Ознака:
`snapshot.next == ('risky_tools',)`. Порівняйте з кроком 7, де після
нормального завершення це поле було порожнє.

Далі — те, заради чого HITL існує: **людині показують, що саме агент
збирається зробити**. Останнє `AIMessage` містить `tool_calls` з іменем
інструмента й аргументами. Жодного рядка коду ще не виконано.

> HITL корисний рівно настільки, наскільки зрозуміло, що показують людині.
> `{"path": "report.txt", "content": "..."}` — зрозуміло. Якби там був
> бінарний блоб чи SQL на 40 рядків, оператор натиснув би «дозволити» не
> дивлячись. Це називається rubber-stamping і є головною хворобою HITL.

`thread_id` генерується новий на кожен прогін
(`f"hitl-demo-{uuid.uuid4().hex[:8]}"`), щоб два сценарії не змішувались.

## Approve

```python
result = hitl_agent.invoke(None, config=config)
```

**`None` замість вхідних даних** — це і є «продовжуй». Жодних нових
повідомлень, граф просто йде далі з місця зупинки: виконує `risky_tools`,
повертається в `agent`, той формулює відповідь.

Перевірка результату матеріальна, не за логами:

```python
print(f"   Файл на диску: {'є' if os.path.exists('report.txt') else 'немає'}")
```

## Reject — найтонше місце

Відмова робиться у **два кроки**: спершу підміняємо результат вузла, потім
продовжуємо граф так само, як при затвердженні.

```python
hitl_agent.update_state(
    config,
    {"messages": [ToolMessage(
        content="Операцію відхилено оператором.",
        tool_call_id=pending.tool_calls[0]["id"]
    )]},
    as_node="risky_tools"
)

result = hitl_agent.invoke(None, config=config)
```

Що тут відбувається:

1. `update_state` записує в нитку новий чекпоінт з нашим повідомленням. Це не
   «продовження графа», а саме **правка стану ззовні**.
2. **`as_node="risky_tools"`** — найважливіший аргумент. Він каже графу:
   «вважай, що цей вузол уже відпрацював і повернув ось це». Рушій зчитує з
   опису графа вихідні ребра `risky_tools` і ставить наступним `agent`. Саме
   тому демо друкує, як `.next` міняється з `('risky_tools',)` на `('agent',)`
   ще **до** будь-якого `invoke`.
3. `ToolMessage` іде **з тим самим `tool_call_id`**, що й у заявки. Редьюсер
   `add_messages` дописує його в стрічку — у заявки з'являється відповідь, і
   історія **валідна**. Без цього наступний запит до моделі або впав би, або
   збив би її з пантелику: провайдери вимагають відповідь на кожен `tool_call`.
4. `invoke(None, config)` продовжує з оновленого стану — рівно той самий
   виклик, що й при затвердженні. Але стартує граф уже з `agent`, тож
   `file_write` **не виконується** і файл на диску не з'являється.
5. Модель бачить «інструмент повернув: операцію відхилено» і коректно
   завершує діалог.

> Чому не можна просто передати `ToolMessage` в `invoke`. Тоді це був би
> **новий вхід** для графа, а не результат вузла: `risky_tools` лишався б у
> `.next` і виконався б. `as_node` — саме те, що робить із повідомлення
> «відповідь замість вузла».

**Ключова теза:** відмова — це не виняток і не обрив. Це **повідомлення в
діалозі**. Агент дізнається про відмову тим самим каналом, що й про
будь-який інший результат, і може відреагувати осмислено. Та сама філософія,
що `{"status": "error"}` у кроці 2.

| | Approve | Reject |
|---|---|---|
| Крок 1 | — | `update_state(..., as_node="risky_tools")` |
| Крок 2 | `invoke(None, config)` | `invoke(None, config)` |
| Вузол `risky_tools` | виконується | не виконується |
| Що бачить модель | справжній результат `file_write` | «відхилено оператором» |
| Побічний ефект | `report.txt` створено | файлу немає |

## Історія чекпоінтів — аудит рішення

```python
for st in list(hitl_agent.get_state_history(config))[::-1]:
    print(st.metadata.get("step"), st.metadata.get("source"), st.next)
```

Наприкінці обох сценаріїв демо друкує всю нитку від старту до фінішу. Дивіться
на колонку `source`:

| `source` | Звідки взявся чекпоінт |
|---|---|
| `input` | новий вхід ззовні (`invoke` з повідомленням) |
| `loop` | звичайний крок графа — вузол відпрацював сам |
| `update` | **втручання людини** через `update_state` |

У сценарії відмови в історії буде рядок із `source="update"` — слід оператора,
який видно й через рік. Це і є **audit trail**: не окремий журнал, який треба
не забути написати, а побічний продукт самої механіки HITL.

## Демо

```python
if os.path.exists("report.txt"):
    os.remove("report.txt")
print("\n🔴 СЦЕНАРІЙ 1: ВІДХИЛЕННЯ")
demo_hitl(approval=False)
print(f"   report.txt на диску: {'є' if os.path.exists('report.txt') else 'немає'}")

print("\n\n🟢 СЦЕНАРІЙ 2: ЗАТВЕРДЖЕННЯ")
demo_hitl(approval=True)
```

Обидва сценарії прогоняються автоматично, файл попередньо видаляється —
**ефект видно очима**: після відмови файлу немає, після дозволу є.

Є ще інтерактивний режим:

```python
answer = input("\n❓ Дозволити запис у файл? [y/N]: ").strip().lower()
approval = answer in ("y", "yes", "т", "так")
```

Дефолт — «ні» (порожній ввід = відмова). Для незворотних операцій це
правильний дизайн.

Консоль тут — заглушка. У реальній системі на місці `input()` стоїть черга
задач, Slack-бот або вебінтерфейс оператора, і між зупинкою та рішенням
минають години. Саме тому стан у SQLite, а не в змінній.

## Що ще існує

- **Правка аргументів перед підтвердженням.** Той самий `update_state()`, але
  без `as_node`: людина міняє `content` чи `path` в останньому `AIMessage`, і
  вузол виконується вже з виправленими аргументами.
  Важливо при цьому обмежувати, **які** поля можна редагувати, — інакше
  підтвердження саме стає каналом неконтрольованих змін.
- **Функція `interrupt()` всередині вузла** + `Command(resume=...)` — гнучкіший
  сучасний механізм: можна повернути дані від людини в конкретну точку. Тут
  узято простіший `interrupt_before`. Важлива деталь на майбутнє: після
  `resume` вузол виконується **з початку**, а не з місця виклику `interrupt`.
- **Таймаут на рішення.** Якщо людина не відповіла ніколи, нитка просто висить
  у базі. У продакшені потрібні TTL та ескалація.

## Перевірити

```bash
rm -f report.txt
.venv/bin/python step9_hitl.py
ls -la report.txt        # після обох сценаріїв файл є
```

Інтерактивно — натисніть самі:

```bash
rm -f report.txt
.venv/bin/python step9_hitl.py --ask
```

Побачити паузу «руками», без демо-функції:

```bash
.venv/bin/python -c "
from langgraph.checkpoint.sqlite import SqliteSaver
from step9_hitl import hitl_graph
with SqliteSaver.from_conn_string('test_hitl.db') as cp:
    app = hitl_graph.compile(checkpointer=cp, interrupt_before=['risky_tools'])
    cfg = {'configurable': {'thread_id': 'x1'}}
    app.invoke({'messages':[{'role':'user','content':'Запиши у файл notes.txt текст: привіт'}]}, config=cfg)
    s = app.get_state(cfg)
    print('наступний вузол:', s.next)
    print('заявка:', s.values['messages'][-1].tool_calls)
    import os; print('файл існує?', os.path.exists('notes.txt'))
"
rm -f test_hitl.db
```

Граф зупинився, заявка видно, файлу немає — і так він може стояти скільки
завгодно довго.
