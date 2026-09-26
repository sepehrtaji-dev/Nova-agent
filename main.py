from __future__ import annotations

import os
import threading
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.text import Text
from rich.theme import Theme

from agent.core import NovaCore


theme = Theme(
    {
        "nova": "bold bright_cyan",
        "user": "bold white",
        "muted": "dim",
        "accent": "bright_blue",
        "success": "bright_green",
    }
)

console = Console(theme=theme)


def clear_screen():
    os.system(
        "cls" if os.name == "nt" else "clear"
    )


def render_header():
    title = Text()

    title.append(
        "✦ ",
        style="bright_cyan"
    )

    title.append(
        "NOVA",
        style="bold white"
    )

    title.append(
        "                                      ",
        style="white"
    )

    title.append(
        "qwen 2.5 · Local",
        style="dim"
    )

    console.print(
        Panel(
            title,
            border_style="bright_cyan",
            padding=(0, 1),
        )
    )


def render_user(message: str):
    console.print()

    label = Text()
    label.append(
        "You",
        style="bold white"
    )

    console.print(label)

    console.print(
        Text(
            "─" * 64,
            style="dim"
        )
    )

    console.print(
        Panel(
            message,
            border_style="grey30",
            padding=(0, 1),
            expand=False,
        )
    )


def render_nova(message: str):
    console.print()

    label = Text()
    label.append(
        "Nova",
        style="bold bright_cyan"
    )

    console.print(label)

    console.print(
        Text(
            "─" * 64,
            style="dim"
        )
    )

    try:
        console.print(
            Markdown(message)
        )
    except Exception:
        console.print(message)


def run_agent(
    core: NovaCore,
    message: str,
    result: dict,
    status: dict,
):
    def on_status(message: str):
        status["value"] = message

    core.status_callback = on_status

    try:
        result["response"] = core.ask(
            message
        )

    except Exception as exc:
        result["error"] = exc


def ask(
    core: NovaCore,
    message: str,
):
    result = {}

    status = {
        "value": "Thinking..."
    }

    thread = threading.Thread(
        target=run_agent,
        args=(
            core,
            message,
            result,
            status,
        ),
        daemon=True,
    )

    thread.start()

    with Status(
        "[bright_cyan]Thinking...[/bright_cyan]",
        spinner="dots",
        console=console,
    ) as live_status:

        while thread.is_alive():

            current = status.get(
                "value",
                "Thinking..."
            )

            live_status.update(
                f"[bright_cyan]{current}[/bright_cyan]"
            )

            time.sleep(0.05)

    if "error" in result:
        raise result["error"]

    return result.get(
        "response",
        "I couldn't generate a response."
    )


def main():

    clear_screen()

    console.print()

    render_header()

    console.print(
        Text(
            "\n  Local AI agent · Tools enabled · Private\n",
            style="dim",
        )
    )

    core = NovaCore()

    while True:

        try:
            console.print()

            message = Prompt.ask(
                "[bold white]›[/bold white]"
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            break

        if not message:
            continue

        if message.lower() in {
            "exit",
            "quit",
            "/exit",
        }:
            break

        if message.lower() in {
            "/clear",
            "/reset",
        }:
            clear_screen()
            render_header()
            continue

        render_user(message)

        try:
            response = ask(
                core,
                message,
            )

            render_nova(
                response
            )

        except KeyboardInterrupt:

            console.print(
                "\n[dim]Cancelled.[/dim]"
            )

        except Exception as exc:

            console.print(
                Panel(
                    "[red]Nova encountered an error:[/red]"
                    f"\n\n{exc}",
                    border_style="red",
                    padding=(0, 1),
                )
            )

    console.print(
        "\n[dim]Nova session ended.[/dim]"
    )


if __name__ == "__main__":
    main()