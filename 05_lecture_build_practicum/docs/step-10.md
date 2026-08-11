# Крок 10 — тести

`test_agents.py`, 152 рядки: 20 швидких тестів + 1 «живий».

```bash
.venv/bin/python -m pytest test_agents.py -v                  # 20 тестів, ~1 секунда
RUN_LIVE_TESTS=1 .venv/bin/python -m pytest test_agents.py -v # + живий виклик моделі
```

## «Агент недетермінований, як його тестувати?»

Недетермінована в ньому **лише модель**. Усе інше — звичайний код.

| Шар | Детермінований? | Як тестувати | Є у файлі |
|---|---|---|---|
| Pydantic-схеми | так | юніт-тести, мілісекунди | 13 тестів |
| Інструменти | так (крім мережевих) | юніт-тести | 7 тестів |
| Топологія графа | так | прогін із фейковою моделлю | немає |
| Поведінка моделі | ні | живі тести, метрики якості | 1 тест |

Основний обсяг тестів пишеться на перші два шари — там немає ні мережі, ні
плати за токени, ні випадкових падінь. І саме там живуть помилки безпеки.

## Схеми імпортуються, а не копіюються

```python
from step2_tools import (
    CalcInput, DateTimeInput, FileWriteInput, HttpInput,
    WikiInput, calculator, current_datetime, file_write,
)
```

У конспекті схеми дублювались у файл тестів (через `%%writefile` у Colab).
Тут імпортуються. Це не стиль, це суть: скопійована схема перевіряє копію, а
не робочий код. Тест, що дублює об'єкт тестування, зелений завжди й не
означає нічого.

## Тести схем — це насправді тести безпеки

```python
def test_calc_input_valid(self):
    inp = CalcInput(expression="2 + 2")
    assert inp.expression == "2 + 2"

def test_calc_input_invalid_chars(self):
    with pytest.raises(ValidationError):
        CalcInput(expression="import os; os.system('rm -rf /')")
```

Схема конструюється **напряму**, без інструмента й без агента — це
самостійний об'єкт зі своїм контрактом.

| Тест | Клас вразливості |
|---|---|
| `test_calc_input_invalid_chars` | ін'єкція коду |
| `test_calc_input_too_long` | перевантаження довгим вводом |
| `test_file_write_path_traversal` | вихід із теки через `../` |
| `test_file_write_absolute_path` | абсолютний шлях `/etc/passwd` |
| `test_http_input_no_scheme` | невалідний URL |
| `test_http_input_timeout_out_of_range` | вихід за межі ресурсу |
| `test_wiki_input_invalid_lang` | значення поза допустимою множиною |

Для агента це не «додаткові» тести, а основні: аргументи генерує модель за
текстом, який може прийти від кого завгодно.

Поруч із негативними обов'язково є **позитивні**:

```python
def test_http_input_valid(self):
    inp = HttpInput(url="https://example.com")
    assert inp.url == "https://example.com"
    assert inp.timeout_sec == 10          # значення за замовчуванням
```

Без них легко отримати схему, яка відхиляє геть усе, — і тести будуть
зелені.

Усюди навмисно стоїть саме `pytest.raises(ValidationError)`, а не ширший
`pytest.raises(Exception)`. `ValidationError` — виняток, який кидає Pydantic,
коли дані не пройшли схему. Якщо ловити просто `Exception`, тест пройде навіть
при `TypeError` через одруківку в коді — і замаскує справжню помилку. Вужчий
виняток перевіряє саме те, що мало статись: спрацювала валідація, а не
випадково щось інше.

## Тести інструментів

```python
def test_calculator_power(self):
    out = json.loads(calculator.invoke({"expression": "2^10 + 3^5"}))
    assert out["status"] == "ok"
    assert out["result"] == 1267
```

Це **регресійний тест на конкретний баг**: `numexpr` не розуміє `^` як степінь,
тому в інструменті стоїть `replace("^", "**")`. 1024 + 243 = 1267. Заберіть
заміну — тест почервоніє. Так фіксують знайдену помилку, щоб вона не
повернулась.

```python
def test_calculator_division_by_zero_is_handled(self):
    out = json.loads(calculator.invoke({"expression": "1/0"}))
    assert out["status"] in ("ok", "error")
```

Тут перевіряється **інваріант, а не значення**: чим би не скінчилось ділення
на нуль, інструмент зобов'язаний повернути валідний JSON зі `status` і не
кинути виняток назовні. Це тест того самого контракту з кроку 2.

```python
def test_file_write_creates_file(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = json.loads(file_write.invoke({"path": "out.txt", "content": "привіт"}))
    assert out["status"] == "ok"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "привіт"
```

Дві стандартні фікстури pytest: `tmp_path` — тимчасова тека, `monkeypatch.chdir`
— перехід у неї на час тесту. Тест справді пише файл, але в пісочниці й не
смітить у репозиторії.

```python
def test_calculator_rejects_injection(self):
    with pytest.raises(ValidationError):
        calculator.invoke({"expression": "__import__('os').system('ls')"})
```

Той самий випадок, що в тестах схем, але через `tool.invoke` — перевіряється,
що валідація справді **під'єднана** до інструмента. Схема може бути
правильною, а `args_schema` — незазначеною; цей тест ловить саме таку помилку
збірки.

## Живий тест — окремо, за прапорцем

```python
@pytest.mark.skipif(not os.getenv("RUN_LIVE_TESTS"),
                    reason="Живий виклик LLM: запускати з RUN_LIVE_TESTS=1")
class TestReActLive:
    def test_react_uses_calculator(self):
        from langchain_core.messages import HumanMessage, ToolMessage

        from step3_react import react_agent

        result = react_agent.invoke(
            {"messages": [HumanMessage(content="Скільки буде 1234 * 5678 + 99?")]}
        )
        used = [m.name for m in result["messages"] if isinstance(m, ToolMessage)]
        assert "calculator" in used
        assert result["messages"][-1].content
```

Помітили `HumanMessage(...)` замість словника `{"role": "user", "content": ...}`?
Обидва варіанти працюють у рантаймі, але словник не проходить перевірку типів:
граф очікує список об'єктів-повідомлень, а не довільних словників.

Швидкий набір ганяється постійно, живий — за потреби: він повільний, коштує
грошей і може впасти через 429 у провайдера.

**Найважливіше — що саме стверджується.** Перевіряються два факти:

- **викликано потрібний інструмент** — тобто перевіряється *поведінка*;
- **фінальна відповідь непорожня** — мінімальна перевірка життєздатності.

Чого тест **не** робить: не порівнює відповідь із рядком «7006751».
Формулювання моделі змінюється від запуску до запуску, такий assert падав би
випадково.

> Тестуйте траєкторію, а не текст. Які інструменти викликано, в якому
> порядку, скільки кроків, чи дійшов граф до кінця — усе це набагато
> стабільніше за формулювання.

Ще одна деталь: імпорти `react_agent` і `ToolMessage` зроблені **всередині
методу**. Модуль `step3_react` тягне `step1_setup`, а той падає на `assert`
без `GOOGLE_API_KEY`. Якби імпорт стояв угорі файлу, збір тестів ламався б
навіть для швидкого набору без ключа.

## Чого у файлі немає — і що варто спробувати

- **Тестів графа з фейковою моделлю.** Підмінивши `llm` заглушкою, яка
  повертає заздалегідь задані `tool_calls`, можна детерміновано перевіряти
  топологію: що після `tools` повертаємось в `agent`, що `is_risky_tool` веде
  в потрібну гілку, що `should_continue` завершує за `replan_count`.
- **Тестів захистів із кроку 5.** Вони тестуються підстановкою стану —
  `fresh_state(..., step_count=MAX_STEPS)` це вже готова фікстура.
- **Набору для оцінки якості (eval).** Для якості відповідей потрібні не
  `assert`-и, а метрики на наборі прикладів: частка правильно обраних
  інструментів, частка успішних завершень.

## Перевірити

```bash
.venv/bin/python -m pytest test_agents.py -v
```

Переконатись, що ключ для швидких тестів не потрібен:

```bash
GOOGLE_API_KEY= .venv/bin/python -m pytest test_agents.py -v -k "not Live"
```

Зламати код і подивитись, який тест почервоніє (потім поверніть назад):

```bash
# у step2_tools.py приберіть .replace("^", "**") у calculator
.venv/bin/python -m pytest test_agents.py -v -k power
```

Запустити живий тест:

```bash
RUN_LIVE_TESTS=1 .venv/bin/python -m pytest test_agents.py -v -k Live
```

Написати свій тест захисту з кроку 5 — спробуйте самі:

```python
def test_max_steps_stops_agent():
    from step5_guards import guarded_agent, fresh_state, MAX_STEPS
    r = guarded_agent.invoke(fresh_state("Хто такий Тарас Шевченко?", step_count=MAX_STEPS))
    assert "ліміт" in r["messages"][-1].content.lower()
```
