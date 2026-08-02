"""REPL для DevMate.

`/usage` тут не для краси: саме він показує, як росте `prompt_tokens`
від ходу до ходу — і чому пам'яті потрібен ліміт.
"""

from rich.console import Console
from rich.panel import Panel

from . import config, llm, tools
from .agent import Agent

console = Console()

HELP = "/usage — токени   /history — розмір контексту   /quit — вихід"


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


def main() -> int:
    agent = Agent(on_tool=show_tool)
    console.print(
        Panel(
            f"[bold]DevMate[/] · {config.MODEL} · {config.WORKSPACE}\n"
            f"інструменти: {', '.join(tools.HANDLERS)}\n"
            f"[yellow]Пам'яті немає: після виходу агент забуде все.[/]\n{HELP}",
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

        try:
            console.print(Panel(agent.run_turn(text), title="DevMate", border_style="blue"))
        except Exception as exc:
            console.print(f"[red]помилка:[/] {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
