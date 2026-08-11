# Крок 1 — середовище і модель

`step1_setup.py`, 71 рядок. Найнудніший файл — і найважливіший: усі дев'ять
наступних кроків імпортують звідси три речі: `llm`, `logger` і `get_text`.

## Ключ береться з `.env` поруч зі скриптом

```python
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
assert os.getenv("GOOGLE_API_KEY"), "Встановіть GOOGLE_API_KEY у .env ..."
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
```

Три деталі, на яких легко втратити час:

**Шлях будується від `__file__`, а не від поточної теки.** Якби було просто
`load_dotenv(".env")`, запуск `python 05_lecture_build_practicum/step3_react.py` з кореня
репозиторію ключа б не знайшов. Класична пастка.

**`assert` замість тихого падіння.** Без ключа програма впаде одразу з
зрозумілим текстом, а не десь усередині HTTP-клієнта з помилкою 401.

**Модель — змінна оточення з дефолтом.** У конспекті стоїть `gemini-2.5-pro`,
у демо — швидша й дешевша `gemini-3.5-flash-lite`. Щоб змінити, код чіпати не
треба, достатньо рядка в `.env`:

```
GEMINI_MODEL=gemini-2.5-pro
```

## Модель — це просто HTTP-клієнт з налаштуваннями

```python
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0.2,
    max_output_tokens=1024,
    timeout=60,
    max_retries=6,
)
```

| Параметр | Навіщо саме таке значення |
|---|---|
| `temperature=0.2` | агентові потрібна передбачуваність, а не креативність |
| `max_output_tokens=1024` | стеля довжини відповіді — і стеля вартості запиту |
| `timeout=60` | без нього завислий запит підвісить увесь граф |
| `max_retries=6` | на безкоштовному тарифі Gemini віддає 429 «забагато запитів» |

`max_retries` тут не «про всяк випадок»: крок 6 робить виклики пачками й без
ретраїв просто не доживає до кінця. Це перший, найдешевший рівень надійності
агента. Другий рівень з'явиться в кроці 6 — там ретрай стоятиме вже навколо
бізнес-логіки, бо модель уміє відповісти успішно, але порожньо.

## `get_text` — хелпер, без якого демо друкує сміття

```python
def get_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content)
```

**Проблема.** У OpenAI `message.content` — рядок. У Gemini через
`langchain-google-genai` це буває **список блоків**:

```python
[{'type': 'text', 'text': 'Привіт'}]
```

Код, написаний за туторіалом під OpenAI, не падає — він мовчки друкує
пітонівський `repr` списку. На екрані з'являється
`[{'type': 'text', 'text': 'Привіт'}]`, і незрозуміло, що зламалось.

`get_text` зводить обидва формати до звичайного рядка. Він використовується
скрізь, де щось друкується: `step3_react.py:72`, `step5_guards.py:130`,
`step6_plan_execute.py:104`, `step7_checkpointer.py:41`, `step8_rag.py:163`,
`step9_hitl.py:114`.

**Висновок ширший за цей хелпер.** Гасло LangChain — «єдиний інтерфейс до
будь-якої моделі» — правдиве лише частково. Уніфікується виклик, але не
формат відповіді, не підтримка JSON-режиму (побачите в кроці 4), не поведінка
при помилках. Плануючи заміну провайдера, розраховуйте не на «поміняти один
рядок», а на прогін усіх тестів.

## Прибирання шуму в логах

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*fixed sampling defaults.*")
```

Без цих рядків екран заливають трейси HTTP-клієнта й попередження Chroma.
Останній фільтр — про те, що `gemini-3.5-flash-lite` ігнорує `temperature` і
попереджає про це **при кожному** виклику; за один прогін кроку 6 це десятки
рядків.

Дрібниця, але вона визначає, чи можна взагалі щось розібрати у виводі.

## Демо

```python
if __name__ == "__main__":
    print("✅ Середовище підготовлено. Модель:", llm.model)
    reply = llm.invoke("Відповідай українською. Скажи одним реченням, що ти працюєш.")
    print("🤖", get_text(reply.content))
```

`llm.invoke(рядок)` — найпростіший можливий виклик: без графа, без
інструментів, без стану. Запам'ятайте цю форму: усе наступне — надбудови над
нею, а внизу завжди один HTTP-запит до моделі.

## Перевірити

```bash
.venv/bin/python step1_setup.py
```

Далі — переконатись, що `get_text` справді потрібен:

```bash
.venv/bin/python -c "
from step1_setup import llm
r = llm.invoke('Скажи одне слово українською')
print(repr(r.content))          # ось у якому вигляді приходить відповідь
"
```

І подивитись, що ще є у відповіді, крім тексту:

```bash
.venv/bin/python -c "
from step1_setup import llm
r = llm.invoke('Привіт')
print(r.usage_metadata)         # скільки токенів коштував запит
"
```
