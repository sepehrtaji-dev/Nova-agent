from __future__ import annotations

import os
import threading
import time
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
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
        "warning": "bright_yellow",
        "error": "bright_red",
        "tool": "bright_magenta",
    }
)

console = Console(theme=theme)


TOOL_NAMES = {
    "web_search": ("WEB", "bright_blue"),
    "terminal": ("TERM", "bright_yellow"),
    "read_file": ("READ", "bright_cyan"),
    "write_file": ("WRITE", "bright_green"),
    "create_directory": ("MKDIR", "bright_magenta"),
    "list_files": ("LIST", "bright_white"),
}


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def terminal_width():
    return max(70, min(console.width, 120))


def render_header():
    width = terminal_width()

    title = Text()
    title.append("✦ ", style="bright_cyan")
    title.append("NOVA", style="bold white")
    title.append("  ", style="white")
    title.append("LOCAL AI AGENT", style="dim")
    title.append(" " * max(1, width - 48))
    title.append("QWEN 2.5", style="dim")

    console.print(
        Panel(
            title,
            border_style="bright_cyan",
            padding=(0, 1),
            expand=True,
        )
    )

    meta = Text()
    meta.append("  ● ", style="bright_green")
    meta.append("LOCAL", style="bold green")
    meta.append("   ")
    meta.append("● ", style="bright_green")
    meta.append("TOOLS ENABLED", style="bold green")
    meta.append("   ")
    meta.append("● ", style="bright_green")
    meta.append("PRIVATE", style="bold green")

    console.print(meta)
    console.print()


def render_user(message: str):
    console.print()

    label = Text()
    label.append("You", style="bold white")

    console.print(label)
    console.print(
        Text("─" * min(terminal_width(), 80), style="dim")
    )

    console.print(
        Panel(
            message,
            border_style="grey30",
            padding=(0, 1),
            expand=False,
        )
    )


def render_nova(message: str, elapsed: float | None = None):
    console.print()

    label = Text()
    label.append("Nova", style="bold bright_cyan")

    if elapsed is not None:
        label.append(
            f"  ·  {elapsed:.2f}s",
            style="dim",
        )

    console.print(label)

    console.print(
        Text("─" * min(terminal_width(), 80), style="dim")
    )

    try:
        console.print(
            Panel(
                Markdown(message),
                border_style="bright_cyan",
                padding=(0, 1),
                expand=False,
            )
        )
    except Exception:
        console.print(message)


def classify_status(message: str):
    text = str(message).strip()
    lower = text.lower()

    for tool_name, (label, color) in TOOL_NAMES.items():
        if tool_name in lower:
            return label, color, "tool"

    if any(
        word in lower
        for word in (
            "error",
            "failed",
            "failure",
            "exception",
        )
    ):
        return "ERROR", "bright_red", "error"

    if any(
        word in lower
        for word in (
            "success",
            "completed",
            "complete",
            "done",
            "finished",
        )
    ):
        return "DONE", "bright_green", "success"

    if any(
        word in lower
        for word in (
            "plan",
            "planning",
            "replan",
            "deciding",
        )
    ):
        return "PLAN", "bright_magenta", "plan"

    if any(
        word in lower
        for word in (
            "think",
            "thinking",
            "reason",
            "processing",
        )
    ):
        return "THINK", "bright_cyan", "think"

    if any(
        word in lower
        for word in (
            "search",
            "web",
            "internet",
        )
    ):
        return "WEB", "bright_blue", "tool"

    return "NOVA", "bright_cyan", "info"


def build_activity_panel(
    events,
    current_status,
    elapsed,
    event_count,
):
    table = Table(
        show_header=False,
        box=None,
        expand=True,
        padding=(0, 1),
    )

    table.add_column(
        "Time",
        style="dim",
        width=9,
        no_wrap=True,
    )

    table.add_column(
        "Type",
        width=9,
        no_wrap=True,
    )

    table.add_column(
        "Activity",
        ratio=1,
    )

    for event in list(events)[-10:]:
        timestamp = event["time"]
        label = event["label"]
        color = event["color"]
        message = event["message"]

        table.add_row(
            timestamp,
            Text(label, style=f"bold {color}"),
            Text(message, style="white"),
        )

    if not events:
        table.add_row(
            "--:--",
            Text("IDLE", style="dim"),
            Text(
                "Waiting for Nova...",
                style="dim",
            ),
        )

    status_line = Text()
    status_line.append(
        "● ",
        style="bright_cyan",
    )
    status_line.append(
        current_status,
        style="bold white",
    )

    footer = Text()
    footer.append(
        f"  Events: {event_count}",
        style="dim",
    )
    footer.append(
        f"   ·   Elapsed: {elapsed:.1f}s",
        style="dim",
    )

    content = Group(
        status_line,
        Text(""),
        table,
        Text(""),
        footer,
    )

    return Panel(
        content,
        title="[bold bright_cyan]ACTIVITY[/bold bright_cyan]",
        border_style="bright_cyan",
        padding=(0, 1),
        expand=True,
    )


def run_agent(
    core: NovaCore,
    message: str,
    result: dict,
    state: dict,
):
    def on_status(status_message: str):
        if not isinstance(status_message, str):
            status_message = str(status_message)

        status_message = status_message.strip()

        if not status_message:
            return

        label, color, kind = classify_status(status_message)

        state["current"] = status_message

        last = state["last_status"]

        if status_message == last:
            return

        state["last_status"] = status_message

        state["events"].append(
            {
                "time": time.strftime("%H:%M:%S"),
                "label": label,
                "color": color,
                "kind": kind,
                "message": status_message,
            }
        )

        state["event_count"] += 1

    core.status_callback = on_status

    try:
        result["response"] = core.ask(message)
    except Exception as exc:
        result["error"] = exc


def ask(
    core: NovaCore,
    message: str,
):
    result = {}

    state = {
        "current": "Thinking...",
        "last_status": "",
        "events": deque(maxlen=40),
        "event_count": 0,
        "started": time.perf_counter(),
    }

    thread = threading.Thread(
        target=run_agent,
        args=(
            core,
            message,
            result,
            state,
        ),
        daemon=True,
    )

    thread.start()

    with Live(
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        while thread.is_alive():
            elapsed = (
                time.perf_counter()
                - state["started"]
            )

            activity = build_activity_panel(
                state["events"],
                state["current"],
                elapsed,
                state["event_count"],
            )

            live.update(activity)

            time.sleep(0.08)

        elapsed = (
            time.perf_counter()
            - state["started"]
        )

        if "error" in result:
            error_message = str(result["error"])

            error_label, error_color, _ = classify_status(
                error_message
            )

            state["events"].append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "label": error_label,
                    "color": error_color,
                    "kind": "error",
                    "message": error_message,
                }
            )

            live.update(
                build_activity_panel(
                    state["events"],
                    "Request failed",
                    elapsed,
                    state["event_count"],
                )
            )

            time.sleep(0.25)

            raise result["error"]

        live.update(
            build_activity_panel(
                state["events"],
                "Completed",
                elapsed,
                state["event_count"],
            )
        )

        time.sleep(0.25)

    return (
        result.get(
            "response",
            "I couldn't generate a response.",
        ),
        elapsed,
    )


def render_help():
    console.print()

    table = Table(
        title="Nova Commands",
        border_style="bright_cyan",
        expand=False,
    )

    table.add_column(
        "Command",
        style="bright_cyan",
    )

    table.add_column(
        "Action",
        style="white",
    )

    table.add_row(
        "/clear",
        "Clear the terminal",
    )

    table.add_row(
        "/reset",
        "Reset the terminal view",
    )

    table.add_row(
        "/help",
        "Show available commands",
    )

    table.add_row(
        "/exit",
        "Exit Nova",
    )

    table.add_row(
        "quit",
        "Exit Nova",
    )

    console.print(table)


def main():
    clear_screen()
    render_header()

    console.print(
        Panel(
            Text.from_markup(
                "[bold white]Nova is ready.[/bold white]\n"
                "[dim]Ask anything. Nova can plan, search the web, "
                "use terminal tools and work with files.[/dim]"
            ),
            border_style="grey30",
            padding=(0, 1),
            expand=True,
        )
    )

    core = NovaCore()

    while True:
        try:
            console.print()

            message = Prompt.ask(
                "[bold bright_cyan]›[/bold bright_cyan]"
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            break

        if not message:
            continue

        command = message.lower()

        if command in {
            "exit",
            "quit",
            "/exit",
        }:
            break

        if command in {
            "/clear",
            "/reset",
        }:
            clear_screen()
            render_header()
            continue

        if command == "/help":
            render_help()
            continue

        render_user(message)

        try:
            response, elapsed = ask(
                core,
                message,
            )

            render_nova(
                response,
                elapsed,
            )

        except KeyboardInterrupt:
            console.print(
                "\n[warning]Request interrupted.[/warning]"
            )

        except Exception as exc:
            console.print()

            console.print(
                Panel(
                    Text.from_markup(
                        "[bold red]Nova encountered an error[/bold red]\n\n"
                        f"{exc}"
                    ),
                    border_style="red",
                    padding=(0, 1),
                    expand=False,
                )
            )

    console.print()

    console.print(
        Panel(
            "[dim]Nova session ended.[/dim]",
            border_style="grey30",
            padding=(0, 1),
            expand=False,
        )
    )


if __name__ == "__main__":
    main()