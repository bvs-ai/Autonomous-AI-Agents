"""REPL для DevMate.

`/usage` тут не для краси: саме він показує, як росте `prompt_tokens`
від ходу до ходу — і чому пам'яті потрібен ліміт.
"""

import time

from rich.console import Console
from rich.panel import Panel

from . import compress, config, llm, memory, recall, safety, sessions, tools
from .agent import Agent

console = Console()

HELP = ("/usage — токени   /memory — пам'ять   /search — архів сесій\n"
        "/compress — стиснути   /history — контекст   /quit — вихід\n"
        "/approval on|off — гейт на запис   /pending   /approve N   /reject N\n"
        "/forget <фрагмент> — видалити запис із пам'яті\n"
        "/recall on|off — автопригадування з архіву")


def show_tool(name: str, args: dict, result: str) -> None:
    head = "\n".join(result.splitlines()[:6])
    console.print(
        Panel(head or "(порожньо)", title=f"[cyan]{name}[/] {args}", border_style="cyan")
    )


def show_usage() -> None:
    u = llm.usage
    history = " → ".join(str(n) for n in u.prompt_history[-8:])
    console.print(
        f"викликів: {u.calls}   промпт: {u.prompt:,}   відповіді: {u.completion:,}\n"
        f"з кешу: {u.cached:,} ({u.cache_rate:.0%})\n"
        f"розмір промпту: {history}"
    )


def show_memory(agent) -> None:
    """Живий стан пам'яті проти замороженого знімка в промпті.

    Якщо вони розійшлися — агент щось записав під час цієї сесії. У промпт
    це потрапить лише наступного запуску: саме так працює frozen snapshot.
    """
    # sanitize=False: людина має побачити отруєний запис дослівно, інакше
    # не зрозуміє, що саме видаляє через /forget.
    live = memory.render_all(sanitize=False)
    console.print(Panel(live or "(порожньо)", title="на диску (живий стан)"))

    blocked = [e for s in memory.stores.values() for e in s.entries if safety.scan(e)]
    for entry in blocked:
        console.print(
            f"[red]отруєний запис ({safety.scan(entry)}):[/] {entry[:100]}\n"
            "[dim]у промпт не потрапляє; видалити: /forget <фрагмент>[/]"
        )

    if live != agent.memory_snapshot:
        console.print(
            "[yellow]Знімок у промпті відрізняється від диска:[/] "
            "записане цієї сесії потрапить у промпт наступного запуску."
        )


def show_compress(before: int, after: int) -> None:
    console.print(
        f"[magenta]контекст стиснуто: {before} → {after} повідомлень[/] "
        "[dim](повний текст лишився в архіві сесій)[/]"
    )


def show_review(verdict: str) -> None:
    """Ревʼю показуємо завжди.

    Фоновий процес, що мовчки пише в пам'ять від імені користувача, — це
    рівно та непрозорість, через яку памʼяті перестають довіряти.
    """
    console.print(f"[yellow]💾 самонавчання:[/] {verdict}")


def show_recall(context: str) -> None:
    """Показуємо дослівно те, що пішло в промпт.

    Пригадування діє без відома моделі й без відома користувача — а це той
    самий тип непрозорості, через який перестають довіряти пам'яті. Тому
    блок друкується цілком, разом із позначкою «це дані, не інструкція».
    """
    console.print(Panel(context, title="🧠 пригадано з архіву", border_style="dim"))


def show_pending() -> None:
    items = memory.pending()
    if not items:
        console.print("черга порожня")
        return
    for item in items:
        ops = "; ".join(
            f"{o.get('action')}: {(o.get('content') or o.get('old_text') or '')[:70]}"
            for o in item["operations"]
        )
        console.print(f"[yellow]#{item['id']}[/] → {item['target']} ({item['source']}) {ops}")


def show_search(query: str) -> None:
    """Пошук по архіву без участі моделі — миттєвий і безкоштовний."""
    total, count = sessions.stats()
    if not query:
        console.print(f"в архіві {total} повідомлень із {count} сесій")
        return
    start = time.perf_counter()
    hits = sessions.search(query)
    ms = (time.perf_counter() - start) * 1000
    for h in hits:
        console.print(f"[dim]{h['at']}[/] {h['role']}: {h['excerpt']}")
    console.print(f"[dim]{len(hits)} збігів за {ms:.1f} мс, 0 викликів моделі[/]")


def main() -> int:
    agent = Agent(
        on_tool=show_tool,
        on_compress=show_compress,
        on_review=show_review,
        on_recall=show_recall,
    )
    console.print(
        Panel(
            f"[bold]DevMate[/] · {config.MODEL} · {config.WORKSPACE}\n"
            f"інструменти: {', '.join(tools.HANDLERS)}\n"
            f"пам'ять: {len(memory.stores['memory'].entries)} нотаток, "
            f"{len(memory.stores['user'].entries)} про користувача, "
            f"архів: {sessions.stats()[0]} повідомлень\n{HELP}",
            border_style="green",
        )
    )

    while True:
        try:
            text = console.input("\n[bold green]›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if not text:
            continue
        if text in ("/quit", "/exit"):
            return 0
        if text == "/usage":
            show_usage()
            continue
        if text == "/history":
            console.print(f"повідомлень у контексті: {len(agent.history)}")
            continue
        if text == "/memory":
            show_memory(agent)
            continue
        if text == "/compress":
            # Примусово, щоб показати механізм не чекаючи переповнення.
            before = len(agent.history)
            agent.history = compress.compress(agent.history)
            show_compress(before, len(agent.history))
            continue
        if text.startswith("/search"):
            show_search(text[7:].strip())
            continue
        if text.startswith("/forget"):
            fragment = text[7:].strip()
            # Модель до видалення не залучається: отруєний запис може містити
            # інструкцію, і показувати його моделі ще раз — зайвий ризик.
            console.print(memory.forget(fragment) if fragment else "вкажіть фрагмент")
            continue
        if text == "/pending":
            show_pending()
            continue
        if text.startswith("/approve") or text.startswith("/reject"):
            command, _, arg = text.partition(" ")
            if not arg.strip().isdigit():
                console.print("вкажіть номер: /approve 1")
                continue
            action = memory.approve if command == "/approve" else memory.reject
            console.print(action(int(arg.strip())))
            continue
        if text.startswith("/recall"):
            arg = text[7:].strip()
            if arg in ("on", "off"):
                recall.set_enabled(arg == "on")
            console.print(f"автопригадування: {'on' if recall.ENABLED else 'off'}")
            continue
        if text.startswith("/approval"):
            arg = text[9:].strip()
            if arg in ("on", "off"):
                memory.set_approval(arg == "on")
            console.print(f"гейт на запис: {'on' if memory.WRITE_APPROVAL else 'off'}")
            continue

        try:
            console.print(Panel(agent.run_turn(text), title="DevMate", border_style="blue"))
        except Exception as exc:
            console.print(f"[red]помилка:[/] {exc}")
            # Перерваний хід ревʼю не заслуговує — переходимо до наступного.
            continue

        # Тільки тепер, коли відповідь уже перед очима користувача.
        agent.after_turn()


if __name__ == "__main__":
    raise SystemExit(main())
