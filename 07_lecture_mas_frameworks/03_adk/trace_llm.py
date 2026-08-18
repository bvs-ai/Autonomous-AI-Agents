"""Найпростіший трейс для ADK: що пішло в модель і що вона відповіла.

Той самий інструмент, що й у двох інших гілках демо, тільки точка підключення
своя. У CrewAI це шина подій, у MAF — middleware, в ADK — **плагін**: клас із
методами `before_model_callback` / `after_model_callback`, який рантайм сам
викликає навколо кожного звернення до моделі.

Підключення — один рядок у `g1_agent.py`:

    App(name=APP_NAME, root_agent=agent, plugins=[trace_llm.plugin])

Плагін реєструється на застосунок, а не на агента, тому в кроках 2 і 3 він
працює для ВСІХ агентів графа без жодної додаткової правки.

Звідки береться інформація. ADK не дає нам сирий HTTP-запит: до колбеку
приходить `LlmRequest` — типізований об'єкт із трьома цікавими полями:

    llm_request.config.system_instruction   інструкція агента (окремо!)
    llm_request.contents                    уся історія розмови
    llm_request.config.tools                оголошення інструментів

Відповідь приходить як `LlmResponse` з `content` і `usage_metadata`. Це той
самий `Event`, що ви бачили в циклі `async for` у `g1`, лише перехоплений
на пів кроку раніше — до того, як рантайм додасть його в сесію.

Запит друкується повністю щоразу, і це не марнотратство виводу, а суть:
у моделі немає сесії, тож на кожному виклику історія летить наново
і оплачується наново. Повторення на екрані — це і є те, за що заплачено.

Вмикається одним рядком:  import trace_llm; trace_llm.on()
Якщо на екрані задовго:   trace_llm.on(limit=300)
"""
from google.adk.plugins.base_plugin import BasePlugin

ENABLED = False
LIMIT: int | None = None  # None — друкувати повністю; число — обрізати


def on(limit: int | None = None) -> None:
    """Вмикає трейс. Викликати до запуску."""
    global ENABLED, LIMIT
    ENABLED, LIMIT = True, limit


def _fmt(text: object) -> str:
    """Тіло повідомлення друкується з початку рядка, без відступів."""
    s = str(text)
    if LIMIT is not None and len(s) > LIMIT:
        return " ".join(s.split())[:LIMIT] + " […]"
    return s


def _parts(content) -> list[str]:
    """Розкладає Content на людські рядки.

    `Part` — union-тип: заповнене рівно одне поле з півтора десятка. Нас
    цікавлять три — текст, виклик інструмента, його результат.
    """
    out: list[str] = []
    for p in getattr(content, "parts", None) or []:
        if p.function_call:
            out.append(f"    ⚙ виклик {p.function_call.name}({_fmt(p.function_call.args)})")
        elif p.function_response:
            out.append(f"    ↩ результат {_fmt(p.function_response.response)}")
        elif p.text:
            out.append(_fmt(p.text))
        else:
            out.append("    (частина без тексту)")
    return out


class _Trace(BasePlugin):
    """Плагін ADK: друкує кожне звернення до моделі й відповідь на нього."""

    def __init__(self) -> None:
        super().__init__(name="trace_llm")
        self.n = 0  # наскрізний номер виклику LLM за весь прогін

    async def before_model_callback(self, *, callback_context, llm_request):
        if not ENABLED:
            return None

        self.n += 1
        # Хто саме зараз ходить у модель — ADK кладе ім'я агента в контекст.
        print(f"\n{'━' * 70}\n[{self.n}] ▸ {callback_context.agent_name}")

        # Інструкція агента їде окремим полем, а не повідомленням, — рівно як
        # у MAF. Без неї на екрані був би не весь оплачений контекст.
        if instruction := llm_request.config.system_instruction:
            print("--- IN system_instruction (окреме поле, не повідомлення):")
            print(_fmt(instruction))

        for content in llm_request.contents:
            print(f"--- IN {content.role}:")
            for line in _parts(content) or ["(порожньо)"]:
                print(line)

        # Оголошення інструментів теж оплачуються токенами, хоч їх ніхто
        # не «писав» у промпт: ADK збирає їх із сигнатур функцій.
        names = [
            d.name
            for tool in llm_request.config.tools or []
            for d in getattr(tool, "function_declarations", None) or []
        ]
        if names:
            print(f"--- IN tools: {', '.join(names)}")

        return None  # None — не втручаємось, запит іде в модель як був

    async def after_model_callback(self, *, callback_context, llm_response):
        if not ENABLED:
            return None

        print("--- OUT:")
        for line in _parts(llm_response.content) or ["(порожньо)"]:
            print(line)

        if usage := llm_response.usage_metadata:
            print(
                f"--- токени: prompt={usage.prompt_token_count or 0} "
                f"completion={usage.candidates_token_count or 0}"
            )
        return None


plugin = _Trace()
