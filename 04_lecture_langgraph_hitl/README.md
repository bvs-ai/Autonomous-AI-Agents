# Демо до лекції 4 — LangGraph: persistence і Human-in-the-Loop

П'ять запускних демо на справжньому LangGraph 1.2.0 із SQLite-чекпоінтером.
Без LLM і без мережі: дані — детерміновані заглушки, тому вивід однаковий на
кожному запуску і демо не залежить ані від провайдера, ані від інтернету
в аудиторії.

Кожен файл самодостатній: 40–90 рядків, жодних спільних модулів, жодного
argparse. Файл цілком уміщується на екрані — можна показувати код і вивід поряд.

Домен: **платіжний агент** узгоджує переказ 50 000 UAH постачальнику.

## Встановлення

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python m0_reducers.py        # перевірка, що все живе
```

Далі всюди `python` = `.venv/bin/python`.

## Що де

| Файл | Рядків | Тема |
|---|---|---|
| `m0_reducers.py` | 52 | reducer задає семантику каналу, включно зі своїм |
| `m1_approval.py` | 92 | `interrupt()` / `resume`, approval gate |
| `m2_persistence.py` | 75 | падіння, відновлення, time-travel |
| `m3_rubber_stamp.py` | 80 | OWASP ASI09: рендер вирішує, а не дані |
| `m4_parallel.py` | 90 | `Send` fan-out, pending writes, retry |

---

## m0 — reducer задає семантику каналу

```bash
python m0_reducers.py
```

Чотири канали отримують **одне й те саме** оновлення двічі (агент написав
чернетку, людина її виправила). Різниця лише в оголошенні типу:

```python
plain: list                              # без reducer  -> перезапис
history: Annotated[list, operator.add]   # -> накопичення
chat: Annotated[list, add_messages]      # -> оновлення за id
draft: Annotated[list, versioned]        # -> свій reducer: нумерація версій
```

Вивід:

```
plain   (без reducer) : ['правка людини'] <- друге затерло перше
history (operator.add): ['чернетка', 'правка людини'] <- ДУБЛЬ замість правки
chat    (add_messages): [('msg-1', 'правка людини')] <- msg-1 оновлено на місці
draft   (свій reducer): ['v1: чернетка', 'v2: правка людини'] <- кожна правка з номером версії
```

**Репліка:** правка людини має той самий `id="msg-1"`. У `operator.add`
з'являється дубль — в історії діалогу опиняються обидва повідомлення, і модель на
наступному кроці бачить і чернетку, і правку. `add_messages` оновлює повідомлення на
місці. Звідси правило: `operator.add` для списку повідомлень ламає HITL-правку.

Четвертий канал відповідає на питання «а якщо мені потрібен не перезапис і не
конкатенація». Reducer — звичайна функція двох аргументів, жодних базових класів:

```python
def versioned(current: list, update: list) -> list:
    current = current or []
    return current + [f"v{len(current) + 1}: {u}" for u in update]
```

Три речі, які варто проговорити, якщо підуть запитання:

- **Виклик — один на кожне оновлення, а не один на super-step.** Фан-ін двох
  гілок дає два послідовні виклики: `([], ['A'])`, потім `(['A'], ['B'])`.
  Отже, reducer не повинен залежати від порядку гілок — він не гарантований.
- **Повертати новий об'єкт, не мутувати `current`.** Повернуте значення
  йде в чекпоінт; мутація спільного об'єкта бруднить уже збережені снапшоти,
  які дивимось у `m2`.
- **Є штатний обхід reducer'а.** `from langgraph.types import Overwrite`, вузол
  повертає `{"draft": Overwrite(value)}` — значення ставиться напряму. Більше
  одного `Overwrite` на super-step → `InvalidUpdateError`.

Іменована функція, а не лямбда: під час порівняння каналів `_operators_equal`
(`langgraph/channels/binop.py:40-47`) вважає будь-яку пару з лямбдою еквівалентною.

---

## m1 — approval gate: `interrupt()` і `resume` (ядро)

```bash
python m1_approval.py start                 # дійти до interrupt, процес завершується
python m1_approval.py state                 # що лежить у чекпоінті
python m1_approval.py resume approve
```

Граф: `analyze → human_review → execute | END`. `interrupt()` зупиняє вузол,
стан іде в `m1.db` на диск.

Після `start`:

```
[node] analyze: чернетка платежу {...}
[node] human_review: старт (після resume виконається З ПОЧАТКУ)
[interrupt] payload назовні: {"action": {...}, "editable": ["purpose"]}
[checkpoint] стан у m1.db — процес можна завершити
```

`state` показує `graph.get_state()`:

```
[state] .next = ('human_review',)
[state] .values = {'action': {...}}
[state] чекає interrupt: True
```

Три речі, які треба проговорити:

1. **`start` і `resume` — різні процеси.** Перший уже завершився; пауза живе
   в чекпоінтері на диску, а не в пам'яті програми. Саме тому
   `SqliteSaver(:memory:)` у цій схемі марний.
2. **Вузол після resume стартує з початку.** Рядок `human_review: старт`
   друкується **вдруге**. Звідси залізне правило: незворотний side effect —
   лише в `execute`, після approval. Усе, що до `interrupt()`, виконається
   двічі.
3. **`edit` працює за allow-list.** Перевірити спробою виправити суму:

```bash
python m1_approval.py resume edit --set purpose=Узгоджено --set amount=1
```

```
[resume] відповідь людини: {'decision': 'edit', 'edits': {'purpose': ..., 'amount': '1'}}
[state] поза allow-list, відхилено: {'amount'}
[node] execute: переказ 50000 UAH -> ТОВ «Постачальник Плюс»
```

Сума лишилася попередньою. Без allow-list approval сам стає каналом
неконтрольованих змін.

`python m1_approval.py resume reject` — гілка відмови: `execute` не виконується.

> `start` щоразу видаляє `m1.db` і починає з чистого аркуша — проганяти демо можна
> скільки завгодно разів поспіль.

---

## m2 — падіння, відновлення, time-travel

```bash
python m2_persistence.py crash
```

Лінійний конвеєр `collect → validate → execute → report`; `execute` кидає
виняток — імітація сервера, що впав.

```
[node] collect
[node] validate
[node] execute
[error] сервер впав під час execute
[checkpoint] collect/validate вже на диску — стан не втрачено
```

```bash
python m2_persistence.py resume       # ІНШИЙ процес
```

```
[state] .next = ('execute',) | log = ['collect', 'validate']
[node] invoke(None, config) — без переісполнення collect/validate:
[node] execute
[node] report
[state] фінальний log: ['collect', 'validate', 'execute', 'report']
```

**Ключове:** `collect` і `validate` не надрукувалися повторно — вони не
перевиконувалися. `invoke(None, config)` означає «продовж звідти, де стояв»
(`None` замість входу). Перед цим `update_state(..., {"crash": False})` — ми
«полагодили» причину падіння просто в стані.

```bash
python m2_persistence.py history
```

```
#0 id=1f19... next=()            log=['collect','validate','execute','report']
#2 id=1f19... next=('execute',)  log=['collect','validate']
#4 id=1f19... next=('validate',) log=['collect']
```

Найсвіжіший чекпоінт — перший. Взяти id будь-якого проміжного рядка і стартувати
нову гілку від нього:

```bash
python m2_persistence.py fork <id>
```

```
[state] лог у гілці: ['collect', 'forked', 'validate', 'execute', 'report']
```

Це time-travel: той самий thread, але інша гілка історії. Основна гілка при цьому
жива — видно повторним `history`.

---

## m3 — rubber stamp / OWASP ASI09

```bash
python m3_rubber_stamp.py                  # спитає approve/reject з клавіатури
python m3_rubber_stamp.py approve reject   # відповіді заздалегідь, для репетиції
```

Одна й та сама дія та один і той самий payload показуються людині двічі.
Різниться **лише рендер на боці клієнта**.

UI A — те, що агент розповідає:

```
🤖 Перевірений постачальник, 12 платежів без претензій, договір погоджено
   юристами. Знижка діє ще 2 години — рекомендую затвердити зараз.
```

UI B — сира дія:

```
  action        : wire_transfer
  amount        : 50000
  vendor        : ТОВ «Постачальник Плюс»
  iban          : UA92 ... 6600 1
  previous_iban : UA21 ... 6610 0
  !! IBAN змінився з минулого платежу: True
```

**Репліка:** у narrative немає ані слова про зміну рахунку — там авторитет («перевірений
постачальник») і терміновість («знижка діє 2 години»). Обидва класичні важелі
тиску. Дані ідентичні, рішення людини змінюється. Це і є ASI09 —
Human-Agent Trust Exploitation: людина перевіряє переконливість пояснення, а не
параметри дії, і approval перетворюється на штамп.

Практичний висновок для аудиторії: на екран погоджувачу виводити raw action і
обчислені сигнали ризику, а пояснення агента — окремим блоком, нижче.

---

## m4 — паралельність: `Send`, pending writes, retry

Агент опитує 4 джерела (`erp`, `bank`, `contracts`, `sanctions`) віялом і
зводить результат. `sanctions` — проблемне.

```bash
python m4_parallel.py fail
```

```
[branch] erp -> ok
[branch] bank -> ok
[branch] contracts -> ok
[error] invoke кинув: ConnectionError('sanctions API timeout')
[state] pending writes успішних гілок: [{'source': 'erp', ...}, ...]
[state] next = ('fetch',) -> superstep НЕ закомічено, merge не виконано
[state] повторний invoke перевиконає ЛИШЕ гілку, що впала:
[error] ConnectionError('sanctions API timeout')
```

Дві половини одного факту:

- superstep не закомічено — `merge` не виконався, `.next` усе ще `('fetch',)`;
- але результати успішних гілок збережено як **pending writes**: при повторному
  `invoke` `[branch] erp/bank/contracts` не друкується вдруге.

«Superstep — транзакція» стосується оновлення стану, а не викидання
вже зробленої роботи. Дорогі успішні виклики не повторюються.

```bash
python m4_parallel.py degrade    # виняток спіймано всередині вузла
```

```
[branch] sanctions -> unavailable (локальна деградація)
[merge] звіт: {'sources': 4, 'holes': ['sanctions']}
```

Граф доходить до кінця, звіт будується з явною діркою — це усвідомлений вибір, а не
мовчазна втрата джерела.

```bash
python m4_parallel.py retry      # RetryPolicy(max_attempts=3)
```

```
[branch] erp -> ok
[branch] bank -> ok
[branch] contracts -> ok
[retry] sanctions: спроба #1
[retry] sanctions: спроба #2
[retry] sanctions: спроба #3
[branch] sanctions -> ok
[merge] звіт: {'sources': 4, 'holes': []}
```

Ретраїться лише гілка, що впала; успішні виконалися рівно по разу.

Окремо показати в коді два рядки:

```python
results: Annotated[list, operator.add]                   # без reducer гілки затруть одна одну
return [Send("fetch", {"source": s}) for s in SOURCES]   # fan-out: N гілок в одному superstep
```

і сортування у `merge` — порядок надходження результатів з паралельних гілок не
гарантований, детермінізм дає лише явне сортування за стабільним ключем.

---

## Що має лишитися в голові у студента

1. Пауза агента живе в чекпоінтері на диску, а не в пам'яті процесу.
2. Після resume вузол виконується з початку → side effect лише після approval.
3. Правка людиною — за allow-list, інакше approval це діра, а не контроль.
4. Чекпоінти дають і відновлення після падіння, і розгалуження історії.
5. Людина затверджує те, що їй **намалювали**; малювати треба факти, а не
   розповідь агента.
6. Падіння паралельної гілки не скасовує роботу успішних — їхні результати лежать
   у pending writes.
