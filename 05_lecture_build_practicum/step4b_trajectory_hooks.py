"""КРОК 4b. Логування траєкторії через callback-хуки LangChain.

ЩО ТАКЕ ХУКИ. Це методи-обробники, які LangChain викликає САМ на початку
і в кінці кожної операції — виклику моделі, виклику інструмента. Ви пишете
клас з потрібними методами, передаєте його в config — і все. Ні граф, ні
вузли, ні інструменти чіпати не треба: хуки лише спостерігають збоку.

НАВІЩО ЦЕ ТУТ. У step4_structured.py траєкторія збирається ПІСЛЯ того, як
агент відпрацював, тому час кроку там — це total/len(messages), тобто
загальний час, поділений порівну. Красиво, але неправда. Хуки спрацьовують
у момент самої події, тож час можна взяти справжній: засікли на старті,
відняли на фініші.

ЯК ЦЕ ЧИТАТИ. Весь файл — це один клас із чотирьох хуків, зібраних у дві
однакові пари:

    on_chat_model_start / on_llm_end   → виклик LLM   (вузол "agent")
    on_tool_start       / on_tool_end  → виклик tool  (вузол "tools")

Обидві пари влаштовані однаково: у *_start запам'ятовуємо час, у *_end
рахуємо різницю й пишемо крок у той самий TrajectoryLogger зі step4.

Хуків у LangChain більше (on_chain_*, on_retriever_*, on_retry, помилки) —
повний список із поясненнями лежить у step4c_callback_hooks.py.

Запуск:  .venv/bin/python step4b_trajectory_hooks.py
"""
import json
import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage

from step1_setup import get_text
from step3_react import react_agent
from step4_structured import TrajectoryLogger


class TrajectoryCallbackHandler(BaseCallbackHandler):
    """Пише траєкторію агента у TrajectoryLogger із чотирьох хуків.

    Наслідуємось від BaseCallbackHandler і перевизначаємо лише ті методи,
    які нам цікаві: для решти подій у базовому класі вже є порожні заглушки.

    Увага: якщо операція впаде з винятком, замість *_end спрацює *_error —
    такий крок у наш журнал не потрапить (як це ловити — у step4c).
    """

    def __init__(self, trajectory_logger: TrajectoryLogger):
        self.tl = trajectory_logger
        self.step = 0
        # run_id — унікальний ідентифікатор операції, однаковий у пари
        # start/end. Саме через нього фініш знаходить «свій» старт: інакше
        # при паралельних викликах інструментів часи переплутаються.
        self.started_at: dict = {}

    def _log(self, run_id, node: str, text: str, tool_name=None) -> None:
        """Спільний фініш для обох пар: рахує тривалість і пише крок."""
        duration = time.time() - self.started_at.pop(run_id)
        self.step += 1
        self.tl.log_step(self.step, node, "", text, duration, tool_name)

    # ── Пара 1: виклик мовної моделі (вузол "agent") ──

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        """Модель почала думати. Для чат-моделей стартовий хук саме цей."""
        self.started_at[run_id] = time.time()

    def on_llm_end(self, response, *, run_id, **kwargs):
        """Модель відповіла. У response лежить готове повідомлення."""
        message = response.generations[0][0].message

        # LLM або відповідає текстом, або просить викликати інструменти.
        requested = [tc["name"] for tc in message.tool_calls]
        # get_text — бо Gemini віддає content списком блоків, і звичайний
        # str() надрукував би "[{'type': 'text', ...}]" замість відповіді.
        text = get_text(message.content) or f"просить інструменти: {', '.join(requested)}"

        self._log(run_id, "agent", text)

    # ── Пара 2: виклик інструмента (вузол "tools") ──

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        """Інструмент почав виконуватись. Спрацьовує на КОЖЕН інструмент окремо."""
        self.started_at[run_id] = time.time()

    def on_tool_end(self, output, *, run_id, **kwargs):
        """Інструмент завершився. output — це ToolMessage, а не рядок."""
        self._log(run_id, "tools", get_text(output.content), output.name)


if __name__ == "__main__":
    query = "Порахуй 2^10 + 3^5 і скажи, який сьогодні день тижня"

    tl = TrajectoryLogger("trajectory_hooks.json")

    t0 = time.time()
    react_agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        # Ось і все підключення: обробник передається у config.
        config={"callbacks": [TrajectoryCallbackHandler(tl)]},
    )
    wall_time = time.time() - t0

    tl.save()

    print("\n" + "═" * 60)
    for e in tl.entries:
        tool = f" [{e['tool']}]" if e["tool"] else ""
        print(f"  {e['step']}. {e['node']}{tool} — {e['duration_sec']:.3f}s")
        print(f"     {e['output'][:100]}")

    print("\n📊 Підсумок:", json.dumps(tl.summary(), ensure_ascii=False))
    print(f"⏱  Сума кроків: {tl.summary()['total_time_sec']:.3f}s "
          f"| увесь запуск: {wall_time:.3f}s")
    # Сума кроків трохи менша за час усього запуску — і так і має бути:
    # поза кроками лишається робота самого графа між викликами.
