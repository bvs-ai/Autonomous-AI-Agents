# Версії: що змінилося з часу конспекту

Довідка для студентів. Конспект лекції писався раніше за це демо, і за цей час
частина API встигла змінитись. Нижче — що саме, і як старі назви з конспекту
відповідають тим, які ви бачите в коді демо.

Усе перевірено живими прогонами у venv цього демо (серпень 2026), а не взято
з документації по пам'яті.

## Коротко

| | У конспекті | У демо | Наскільки боляче |
|---|---|---|---|
| CrewAI | 1.11.0 | **1.15.16** | розбіжностей в API немає |
| Microsoft | AutoGen `autogen-agentchat` 0.7.5 | **`agent-framework-core` 1.14.0** | фреймворк замінено цілком |
| Google ADK | 1.27.4 | **2.7.0** | API конспекту працює, але `deprecated` |
| Модель | `gemini-2.5-flash` | `gemini-3.5-flash-lite` | стара недоступна новим ключам |

## CrewAI — нічого не змінилось

Усі поля, про які говорить конспект, на місці й у 1.15.16: в `Agent` —
`role`, `goal`, `backstory`, `tools`, `llm`, `max_iter`, `allow_delegation`;
в `Task` — `description`, `expected_output`, `agent`, `context`, `guardrail`;
в `Crew` — `agents`, `tasks`, `process`, `manager_llm`, `Process.sequential`
і `Process.hierarchical`.

Єдине: ставити саме 1.11.0 з конспекту не можна, якщо в тому ж оточенні живе
Microsoft Agent Framework — pip не зведе залежності. Потрібен `crewai>=1.15`.

## AutoGen → Microsoft Agent Framework

`autogen-agentchat` заморожений рівно на тій версії 0.7.5, що в конспекті:
AutoGen і Semantic Kernel переведені Microsoft у режим підтримки (лише
багфікси). Наступник — Microsoft Agent Framework, 1.0 у квітні 2026,
зараз 1.14.0. Тому в демо `02_msagent/`, а не AutoGen.

| Концепт лекції | AutoGen 0.7.x (конспект) | Agent Framework 1.14 |
|---|---|---|
| Агент | `AssistantAgent(name, model_client, system_message, tools)` | `client.as_agent(name, instructions, tools)` |
| Клієнт моделі | `OpenAIChatCompletionClient(model=...)` | `GeminiChatClient(model=..., api_key=...)` |
| Послідовна команда | `RoundRobinGroupChat` | `SequentialBuilder` |
| Паралельна робота | — (робили руками) | `ConcurrentBuilder` |
| Спікера обирає LLM | `SelectorGroupChat` | `GroupChatBuilder` + `orchestrator_agent` |
| Swarm / handoff | `Swarm(participants, handoffs=[...])` | `HandoffBuilder` |
| Умови зупинки | `TextMentionTermination`, `MaxMessageTermination` | `TerminationCondition`, `max_rounds` |
| Граф переходів | `GraphFlow` (experimental) | `WorkflowBuilder` + `Workflow` (стабільний) |

Головне тут не таблиця, а те, що **парадигма group chat нікуди не зникла** —
вона просто переїхала в інший пакет. А експериментальний `GraphFlow` став
стабільним ядром: Microsoft рушив туди ж, куди LangGraph йшов від початку, —
до явного графа.

Три місця, де легко спіткнутися: агент створюється через `client.as_agent(...)`
(а не `create_agent(...)`), параметр моделі — `model=` (а не `model_id=`),
інструмент передається **голою Python-функцією**, без декоратора й без схеми.

## Google ADK 1.x → 2.x

Тут м'якше. Код у стилі конспекту — `LlmAgent` + `SequentialAgent` +
`output_key` + шаблон `{research}` в інструкції — **на 2.7.0 працює**.
`SequentialAgent`, `ParallelAgent`, `LoopAgent`, `exit_loop`,
`transfer_to_agent` усі на місці.

Але при запуску друкується попередження — ви побачите його своїми очима
на кроці `g2`:

```
DeprecationWarning: SequentialAgent is deprecated in favor of Workflow
and will be removed in a future version.
Workflow cannot yet be used as an LlmAgent sub-agent.
```

Два висновки з нього. Перший: workflow-агенти з конспекту живі, але позначені
на видалення. Другий, цікавіший: заміна ще **не повна** — друга фраза визнає,
що `Workflow` поки не можна вкласти в `LlmAgent` як sub-agent. Тобто ми бачимо
фреймворк у момент міграції, з двома API одночасно.

| Концепт лекції | ADK 1.x (конспект) | ADK 2.7 |
|---|---|---|
| Послідовно | `SequentialAgent(sub_agents=[...])` | `Workflow` із ланцюжком `Node` |
| Паралельно | `ParallelAgent(sub_agents=[...])` | fan-out + `JoinNode` |
| Цикл | `LoopAgent(max_iterations=...)` + `exit_loop` | ребро назад по графу |
| Передача даних | `output_key` → state → `{key}` | те саме, плюс явні повідомлення між вузлами |
| Надійність вузла | — | `RetryConfig`, `NodeTimeoutError` |
| Handoff | `sub_agents` + `transfer_to_agent` | без змін |

Демо показує обидва API навмисно: крок `g2` — старий `SequentialAgent`
із живим попередженням на екрані, крок `g3` — новий графовий `Workflow`.

## Чому версії в requirements.txt зафіксовані

Не для краси — три піни з чотирьох існують через реальні конфлікти:

- мета-пакет `agent-framework` тягне ~150 залежностей (Azure, boto3, anthropic)
  і **ламає CrewAI** по `pydantic` та `opentelemetry`. Ставимо лише
  `agent-framework-core`, `agent-framework-gemini`,
  `agent-framework-orchestrations`;
- `crewai==1.11.0` з конспекту несумісний з Agent Framework: pip дає
  `ResolutionImpossible`;
- папку з прикладами не можна назвати `crewai/` — вона затінить однойменний
  пакет. Саме тому папки нумеровані: `01_crewai/`, `02_msagent/`, `03_adk/`.

Те, що три незалежні фреймворки від трьох вендорів ставляться поруч і працюють
від одного ключа, — теж результат, і він не безкоштовний.

## Модель і ключ

- `gemini-2.5-flash` із конспекту віддає **404** новим ключам («no longer
  available to new users»). У демо — `gemini-3.5-flash-lite`.
- Один `GOOGLE_API_KEY` обслуговує всі три фреймворки: CrewAI через LiteLLM,
  ADK і Agent Framework — напряму.
- Окремий `GEMINI_API_KEY` задавати не треба: при двох заданих ключах LiteLLM
  друкує попередження й шумить у виводі.

## Що з цього забрати

Одна думка дорожча за всі таблиці вище: **між написанням конспекту й лекцією
один фреймворк устиг померти, другий — оголосити свій основний API застарілим,
а третій не змінився взагалі**. Звідси практичний висновок: вчити треба
парадигму координації (послідовність, group chat, граф, handoff) — вона
переживає зміну імен класів.
