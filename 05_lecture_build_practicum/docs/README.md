# Розбір демо по кроках

Практикум «Крок 1–10»: агент на LangGraph, зібраний з нуля. Один файл коду =
один крок = один документ тут.

Читати краще паралельно з кодом: відкрити `step3_react.py` і `step-3.md` поруч.
Кожен документ закінчується розділом **«Перевірити»** — командами, які варто
запустити самому, щоб побачити описане на екрані.

## Порядок

| Документ | Файл коду | Про що |
|---|---|---|
| [step-0.md](step-0.md) | — | Як влаштований LangGraph: стан, вузли, ребра. Прочитати першим |
| [step-1.md](step-1.md) | `step1_setup.py` | Ключ, модель, `get_text` |
| [step-2.md](step-2.md) | `step2_tools.py` | Інструменти й Pydantic-схеми |
| [step-3.md](step-3.md) | `step3_react.py` | ReAct-агент: цикл модель ⇄ інструменти |
| [step-4.md](step-4.md) | `step4_structured.py`, `step4b_trajectory_hooks.py` | Structured outputs, лог траєкторії, callback-хуки |
| [step-5.md](step-5.md) | `step5_guards.py` | Ліміт кроків, таймаут, детекція повторів |
| [step-6.md](step-6.md) | `step6_plan_execute.py` | Plan-and-Execute |
| [step-7.md](step-7.md) | `step7_checkpointer.py` | Checkpointer: пам'ять між запитами |
| [step-8.md](step-8.md) | `step8_rag.py` | Agentic RAG з ChromaDB |
| [step-9.md](step-9.md) | `step9_hitl.py` | Human-in-the-Loop |
| [step-10.md](step-10.md) | `test_agents.py` | Тести агента |

## Запуск

```bash
cd 05_lecture_build_practicum
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # вписати свій GOOGLE_API_KEY
.venv/bin/python step1_setup.py     # перевірка, що ключ живий
```

Далі — по одному файлу за раз:

```bash
.venv/bin/python step3_react.py
```

Або всі підряд (займе 2–3 хвилини):

```bash
.venv/bin/python run_all.py
.venv/bin/python run_all.py 3 5 9    # тільки вибрані кроки
```

Ключ безкоштовно береться тут: https://aistudio.google.com/apikey

## Файли залежать один від одного

Кожен крок імпортує попередні:

```
step1_setup   → llm, logger, get_text
step2_tools   → схеми, 5 інструментів, safe_tools
step3_react   → SYSTEM_PROMPT, llm_with_tools, react_graph, react_agent
   ↓ використовують: step4, step5, step6, step7, step8, step9
```

Демонстраційна частина кожного файлу схована в `if __name__ == "__main__":`,
тому імпорт не запускає чужі демо. Тобто `from step3_react import react_agent`
дає готовий об'єкт, але не друкує вивід кроку 3.

## Артефакти

Під час запусків з'являються файли: `trajectory.json` (крок 4),
`trajectory_hooks.json` (крок 4b), `checkpoints.db` (крок 7), `chroma_db/`
(крок 8), `hitl_checkpoints.db` і `report.txt` (крок 9). Усі — в `.gitignore`.

Щоб подивитись усе «з нуля»:

```bash
rm -rf chroma_db *.db report.txt trajectory*.json
```

Крок 7 чистить свої нитки сам (`checkpointer.delete_thread(...)` на початку
демо), інакше при повторному запуску агент «пам'ятає» ім'я ще до першого
запиту.
