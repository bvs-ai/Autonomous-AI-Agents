# Крок 7 — checkpointer: пам'ять і відновлення

`step7_checkpointer.py`, 86 рядків, увесь файл — одна демо-функція. Нового
коду графа немає взагалі: береться `react_graph` із кроку 3, змінюється лише
спосіб компіляції.

## Що з'являється

Досі стан жив усередині одного `invoke()` і вмирав разом із ним. Checkpointer
зберігає стан графа **після кожного вузла**, і з'являються три речі:

1. **Пам'ять діалогу між запитами** — другий `invoke` бачить перший.
2. **Відновлення після падіння** — процес упав, стан лишився на диску.
3. **Пауза на людині** — саме на цьому побудований крок 9.

## Компіляція з checkpointer

```python
with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
    persistent_agent = react_graph.compile(checkpointer=checkpointer)
```

**Імпортується `react_graph`, а не `react_agent`** — тобто *опис* графа, і
компілюється заново, з checkpointer. Один опис → різні виконувані об'єкти
залежно від обв'язки. Саме тому крок 3 експортує обидва імені.

**`with` обов'язковий.** `SqliteSaver.from_conn_string` повертає контекстний
менеджер; без `with` з'єднання з базою не відкриється коректно. Наслідок:
увесь агент живе всередині блоку `with`, тому демо оформлене однією функцією.

У справжньому застосунку так незручно, і там використовують
`AsyncSqliteSaver` або `PostgresSaver`, з'єднання яких живе на рівні
застосунку.

## `thread_id` — ідентифікатор сесії

```python
thread_id = "demo-thread-001"
config = {"configurable": {"thread_id": thread_id}}
```

Далі `config` передається **в кожен** `invoke`. Це ключ, за яким checkpointer
знаходить стан. Простими словами — «id чату».

Модель зберігання: `thread_id → ланцюжок чекпоінтів`.

```python
checkpointer.delete_thread("demo-thread-001")
checkpointer.delete_thread("demo-thread-002")
```

Перше, що робить демо, — **стирає обидві нитки**. Без цього другий запуск
скрипта виглядає зламаним: агент відповідає «тебе звати Олексій» ще до Запиту 1,
бо `checkpoints.db` лежить на диску з минулого разу. Це не костиль демо, а сама
суть checkpointer-а: **стан переживає процес**. `delete_thread` — штатний спосіб
прибрати сесію (він же — «видалити історію чату» у справжньому продукті).

Одразу про безпеку: хто контролює `thread_id`, той читає чужий діалог. Якщо
він приходить з фронтенду без перевірки — це діра. У справжній системі ключ
формує сервер із автентифікованого користувача.

## Пам'ять у дії

```python
result1 = persistent_agent.invoke(
    {"messages": [HumanMessage(content="Мене звати Олексій. Запам'ятай це.")]},
    config=config)

result2 = persistent_agent.invoke(
    {"messages": [HumanMessage(content="Як мене звати?")]},
    config=config)
```

Другий виклик передає **тільки нове повідомлення**, а модель усе одно
відповідає «Олексій». Що відбувається:

1. `invoke` отримує зміну `{"messages": [HumanMessage("Як мене звати?")]}`;
2. рушій піднімає за `thread_id` останній чекпоінт;
3. редьюсер `add_messages` **дописує** нове повідомлення до відновленої
   стрічки;
4. вузол `agent` отримує всю історію і надсилає її моделі.

**Модель, як і раніше, не має пам'яті.** У кожному HTTP-запиті їде вся
стрічка повідомлень. «Пам'ять» реалізована на нашому боці, checkpointer-ом.

Прямий наслідок: із довжиною діалогу зростають і вартість, і ризик впертись у
контекстне вікно. Тому в реальних агентах потрібна стратегія обрізання або
підсумовування історії.

## Знімок стану

```python
snapshot = persistent_agent.get_state(config)
print(f"   Кількість повідомлень: {len(snapshot.values.get('messages', []))}")
print(f"   Конфігурація: {snapshot.config}")
print(f"   Наступний вузол: {snapshot.next or '(граф завершено)'}")

history = list(persistent_agent.get_state_history(config))
print(f"   Збережених чекпоінтів у гілці: {len(history)}")
```

| Поле | Що всередині |
|---|---|
| `.values` | сам стан (у нас — `messages`) |
| `.config` | `thread_id` + `checkpoint_id` конкретного чекпоінта |
| `.next` | кортеж вузлів, які виконаються наступними |

**`.next` — найважливіше.** Після нормального завершення він порожній. У
кроці 9 після зупинки там буде `('risky_tools',)` — саме так визначається, що
граф чекає на людину. Запам'ятайте це поле.

**`get_state_history`** повертає всі чекпоінти нитки, від свіжого до старого.
Тут використовується лише для лічильника, але це та сама структура, на якій
працює «подорож у часі»: взяти `config` старого чекпоінта і запустити `invoke`
з нього — граф піде альтернативною гілкою.

Помітьте: чекпоінтів більше, ніж повідомлень у діалозі, бо запис робиться
після **кожного** вузла, включно з `tools`.

## «Відновлення»

```python
restored_agent = react_graph.compile(checkpointer=checkpointer)
result3 = restored_agent.invoke(
    {"messages": [HumanMessage(content="Нагадай, як мене звати, і порахуй 42 * 58")]},
    config=config)
```

Новий екземпляр агента, той самий checkpointer і `thread_id` — контекст на
місці.

Чесно: це **імітація** відновлення в межах одного процесу. Але вона доводить
головне: **агент не володіє станом**. Стан живе в checkpointer, агент —
тимчасовий виконавець. Будь-який екземпляр, піднявши той самий `thread_id`,
продовжить діалог.

Справжню перевірку зробіть самі — вона в розділі «Перевірити».

## Контроль: інший `thread_id`

```python
other = {"configurable": {"thread_id": "demo-thread-002"}}
result4 = restored_agent.invoke(
    {"messages": [HumanMessage(content="Як мене звати?")]}, config=other)
```

Той самий агент, та сама база, інший ключ — імені агент не знає. Це доводить,
що «пам'ять» є властивістю **ключа**, а не агента.

## Перевірити

```bash
.venv/bin/python step7_checkpointer.py
```

Справжнє відновлення — два окремі процеси:

```bash
# перший процес: сказали ім'я
.venv/bin/python -c "
from langgraph.checkpoint.sqlite import SqliteSaver
from step3_react import react_graph
from step1_setup import get_text
with SqliteSaver.from_conn_string('my.db') as cp:
    app = react_graph.compile(checkpointer=cp)
    r = app.invoke({'messages':[{'role':'user','content':'Мене звати Марія. Запамʼятай.'}]},
                   config={'configurable':{'thread_id':'t1'}})
    print(get_text(r['messages'][-1].content))
"

# другий процес: інший запуск python, пам'ять на місці
.venv/bin/python -c "
from langgraph.checkpoint.sqlite import SqliteSaver
from step3_react import react_graph
from step1_setup import get_text
with SqliteSaver.from_conn_string('my.db') as cp:
    app = react_graph.compile(checkpointer=cp)
    r = app.invoke({'messages':[{'role':'user','content':'Як мене звати?'}]},
                   config={'configurable':{'thread_id':'t1'}})
    print(get_text(r['messages'][-1].content))
"
rm my.db
```

Подивитись, що всередині бази — жодної магії:

```bash
sqlite3 checkpoints.db ".tables"
sqlite3 checkpoints.db "select count(*) from checkpoints;"
```

І пройтись по історії чекпоінтів:

```bash
.venv/bin/python -c "
from langgraph.checkpoint.sqlite import SqliteSaver
from step3_react import react_graph
with SqliteSaver.from_conn_string('checkpoints.db') as cp:
    app = react_graph.compile(checkpointer=cp)
    cfg = {'configurable': {'thread_id': 'demo-thread-001'}}
    for s in app.get_state_history(cfg):
        print(s.next, '|', len(s.values.get('messages', [])), 'повідомлень')
"
```
