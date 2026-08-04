"""REPL. Ті самі команди, що в `../01_memory/devmate/cli.py`, інші нутрощі.

    /memory   MEMORY.md              → store.search(("users", uid, "facts"))
    /search   FTS5 по state.db       → store.search(query=) — семантика, не словоформи
    /compress compress.py            → примусовий pre_model_hook
    /approve  своя черга             → Command(resume=True) після interrupt()
    /forget   правка файлу           → store.delete
    /history  довжина списку         → get_state_history(): time travel, якого не було
    /trace    —                      → траєкторія останнього виклику search_kb

Запуск:  python -m devmate_lg.cli
"""
import sys
import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel

from . import agent as agent_mod
from . import rag
from .config import MODEL, RECURSION_LIMIT, USER_ID
from corpus import EmbedUnavailable  # noqa: E402  — після .config, див. agent.py
from .hooks import build_input
from .memory_tools import facts

console = Console()

HELP = ("/memory — факти   /search <запит> — семантичний пошук у памʼяті\n"
        "/compress — що піде в модель   /history — чекпоінти   /trace — цикл RAG\n"
        "/usage — токени   /approve, /reject — гейт запису   /new — нова нить   /quit")


def show_pause(ask: dict) -> None:
    console.print(Panel(f"{ask['fact']}\n\n[dim]/approve або /reject[/]",
                        title="⏸ запис у памʼять чекає на людину", border_style="yellow"))


def waiting(agent, cfg) -> dict | None:
    """Незакритий `interrupt()` цієї нитки.

    Пауза лежить у чекпоінті, а не в памʼяті процесу, тому переживає і вихід із
    REPL, і перезапуск машини. Питати про це стан доводиться самим: спробувати
    просто продовжити діалог не можна — у чекпоінті висить виклик інструмента
    без відповіді, і модель на такій історії падає.
    """
    found = [i.value for task in agent.get_state(cfg).tasks for i in task.interrupts]
    return found[0] if found else None


def turn(agent, cfg, payload) -> None:
    """Хід агента. Перерваний `interrupt()` — не помилка, а стан на паузі."""
    out = agent.invoke(payload, config=cfg, context=agent_mod.Context(USER_ID))
    if out.get("__interrupt__"):
        show_pause(out["__interrupt__"][0].value)
        return
    console.print(Panel(out["messages"][-1].text, title="DevMate", border_style="blue"))


def show_memory(store, query: str = "") -> None:
    for score, text in facts(store, query):
        console.print(f"[dim]{score:.3f}[/] {text}" if score else f"      {text}")


def show_usage(agent, cfg) -> None:
    """Точність нижча, ніж у `llm.py` DevMate: prefix cache провайдер не показує."""
    used = [m.usage_metadata for m in agent.get_state(cfg).values["messages"]
            if getattr(m, "usage_metadata", None)]
    console.print(f"викликів: {len(used)}   промпт: {sum(u['input_tokens'] for u in used):,}   "
                  f"відповіді: {sum(u['output_tokens'] for u in used):,}")


def main() -> int:
    agent, store = agent_mod.build()
    thread = "lecture"
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": RECURSION_LIMIT}
    console.print(Panel(f"[bold]DevMate LG[/] · {MODEL} · нить {thread}\n"
                        f"інструменти: search_kb, remember, forget, run_tests\n{HELP}",
                        border_style="green"))
    # Найкраща демонстрація чекпоінтера: процес помер, а пауза жива.
    if (paused := waiting(agent, cfg)):
        console.print("[yellow]з минулого запуску лишилась пауза:[/]")
        show_pause(paused)

    while True:
        try:
            text = console.input("\n[bold green]›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not text:
            continue

        try:
            if text in ("/quit", "/exit"):
                return 0
            if text == "/memory":
                show_memory(store)
            elif text.startswith("/search"):
                show_memory(store, text[7:].strip())
            elif text == "/compress":
                msgs = agent.get_state(cfg).values.get("messages", [])
                console.print(f"в чекпоінті {len(msgs)} повідомлень → в модель піде "
                              f"{len(build_input(msgs, store))} "
                              "(обрізане + блок памʼяті)")
            elif text == "/history":
                for snap in list(agent.get_state_history(cfg))[:8]:
                    console.print(f"[dim]{snap.config['configurable']['checkpoint_id'][-6:]}[/] "
                                  f"{len(snap.values.get('messages', []))} повідомлень, "
                                  f"далі: {snap.next or '—'}")
            elif text == "/trace":
                console.print("\n".join(f"  {i}. {s}" for i, s in enumerate(rag.LAST_TRACE, 1))
                              or "search_kb ще не викликався")
            elif text == "/usage":
                show_usage(agent, cfg)
            elif text in ("/approve", "/reject"):
                if waiting(agent, cfg):
                    turn(agent, cfg, Command(resume=text == "/approve"))
                else:
                    console.print("нічого не чекає на підтвердження")
            elif text == "/new":
                # Цикл 3: історія порожня, факти в store на місці.
                thread = f"thread-{uuid.uuid4().hex[:6]}"
                cfg = {"configurable": {"thread_id": thread}, "recursion_limit": RECURSION_LIMIT}
                console.print(f"нова нить: {thread}")
            elif text.startswith("/"):
                console.print(HELP)
            elif (paused := waiting(agent, cfg)):
                console.print("[yellow]хід на паузі — спершу /approve або /reject[/]")
                show_pause(paused)
            else:
                turn(agent, cfg, {"messages": [HumanMessage(text)]})
        except EmbedUnavailable as exc:
            console.print(f"[red][ЗУПИНКА][/] {exc}")
        except Exception as exc:  # трейс при аудиторії не показуємо
            console.print(f"[red][ЗУПИНКА][/] {type(exc).__name__}: {str(exc)[:300]}")


if __name__ == "__main__":
    sys.exit(main())

# ── Твоя черга ──
# 1) Спитай щось, чого в нотатках немає (наприклад, про відкат релізу): побач
#    [WEB] і заблокований документ. Прибери `scan()` з `web_fallback` — і
#    подивись, що приїде в промпт замість нього.
# 2) Постав MAX_ATTEMPTS = 1 у config.py. Яка відповідь стає чеснішою, а яка —
#    гіршою? Де межа між упертістю і чесним «не підтверджено»?
# 3) Додай `post_model_hook`, який після кожного ходу пише факти в store сам.
#    Скільки гейтів `scan()` тепер у системі — і чи однакові вони?
