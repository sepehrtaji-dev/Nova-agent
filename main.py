from __future__ import annotations

import os
import threading
import time
from collections import deque

from rich import box
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
    "web_search":       ("WEB",     "bright_blue"),
    "terminal":         ("TERM",    "bright_yellow"),
    "read_file":        ("READ",    "bright_cyan"),
    "write_file":       ("WRITE",   "bright_green"),
    "edit_file":        ("EDIT",    "bright_green"),
    "delete_file":      ("DELETE",  "bright_red"),
    "create_directory": ("MKDIR",   "bright_magenta"),
    "list_files":       ("LIST",    "bright_white"),
    "git":              ("GIT",     "bright_magenta"),
    "desktop":          ("DESKTOP", "bright_yellow"),
    "generate_image":   ("IMAGE",   "bright_blue"),
}

ACCESS_META = {
    "web": ("WEB SEARCH", "Web search access"),
    "git": ("GIT",        "Repository operations"),
    "pc":  ("PC USE",     "Terminal · Files · Desktop OS control"),
}


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def terminal_width():
    return max(78, min(console.width, 132))


def access_pill(name: str, enabled: bool) -> Text:
    label = ACCESS_META[name][0]
    text = Text()

    if enabled:
        text.append("● ", style="bright_green")
        text.append(label, style="bold bright_green")
    else:
        text.append("○ ", style="dim")
        text.append(label, style="dim")

    return text


def render_header(core: NovaCore):
    access = core.get_access()

    header = Table(
        box=None,
        show_header=False,
        expand=True,
        padding=(0, 1),
    )
    header.add_column("brand", ratio=1, no_wrap=True)
    header.add_column("mode", justify="center", no_wrap=True)
    header.add_column("model", justify="right", no_wrap=True)

    brand = Text()
    brand.append("✦ ", style="bright_cyan")
    brand.append("NOVA", style="bold white")
    brand.append("  ", style="white")
    brand.append("LOCAL AI AGENT", style="dim")

    header.add_row(
        brand,
        Text("CHAT / AGENT", style="dim"),
        Text("QWEN 2.5 · 3B", style="dim"),
    )

    console.print(
        Panel(
            header,
            border_style="bright_cyan",
            padding=(0, 0),
            expand=True,
        )
    )

    permissions = Table(
        box=None,
        show_header=False,
        expand=True,
        padding=(0, 1),
    )
    permissions.add_column("web", ratio=1, no_wrap=True)
    permissions.add_column("git", ratio=1, justify="center", no_wrap=True)
    permissions.add_column("pc", ratio=1, justify="right", no_wrap=True)

    permissions.add_row(
        access_pill("web", access["web"]),
        access_pill("git", access["git"]),
        access_pill("pc", access["pc"]),
    )

    console.print(permissions)

    hint = Text()
    hint.append("  /web", style="bright_blue")
    hint.append(" toggle   ", style="dim")
    hint.append("/git", style="bright_magenta")
    hint.append(" toggle   ", style="dim")
    hint.append("/pc", style="bright_green")
    hint.append(" toggle   ", style="dim")
    hint.append("/help", style="white")

    console.print(hint)
    console.print()


def render_welcome():
    content = Text()
    content.append("Nova is ready.\n", style="bold white")
    content.append(
        "Ask naturally. Nova can plan tasks, use enabled tools, "
        "inspect real results, re-plan, and finish the work.\n\n",
        style="dim",
    )
    content.append(
        "Model activity is shown at a high level; private reasoning is never displayed.",
        style="dim italic",
    )

    console.print(
        Panel(
            content,
            title="[bold bright_cyan]SESSION[/bold bright_cyan]",
            border_style="grey30",
            padding=(1, 2),
            expand=True,
        )
    )


def render_user(message: str):
    console.print()
    label = Text()
    label.append("YOU", style="bold white")
    label.append("  ·  MESSAGE", style="dim")

    console.print(label)
    console.print(
        Panel(
            message,
            border_style="grey37",
            padding=(0, 1),
            expand=True,
        )
    )


def render_nova(message: str, elapsed: float | None = None):
    console.print()
    label = Text()
    label.append("NOVA", style="bold bright_cyan")

    if elapsed is not None:
        label.append(f"  ·  {elapsed:.2f}s", style="dim")

    console.print(label)

    try:
        body = Markdown(message)
    except Exception:
        body = Text(str(message))

    console.print(
        Panel(
            body,
            border_style="bright_cyan",
            padding=(0, 1),
            expand=True,
        )
    )


def classify_status(message: str):
    text  = str(message).strip()
    lower = text.lower()

    # Verification results — check first (most specific)
    if text.startswith("✓"):
        return "✓ OK",  "bright_green",  "confirm"
    if text.startswith("✗"):
        return "✗ FAIL", "bright_red",   "error"

    # Tool usage
    for tool_name, (label, color) in TOOL_NAMES.items():
        if tool_name in lower:
            return label, color, "tool"

    # Errors
    if any(w in lower for w in (
        "error", "failed", "failure", "exception", "blocked",
        "invalid", "rejected", "denied"
    )):
        return "ERROR", "bright_red", "error"

    # Verification words
    if any(w in lower for w in ("verif", "confirm", "checking")):
        return "CHECK", "bright_cyan", "verify"

    # Success
    if any(w in lower for w in (
        "success", "completed", "complete", "done", "finished"
    )):
        return "DONE", "bright_green", "success"

    # Planning
    if any(w in lower for w in (
        "plan", "planning", "replan", "deciding", "understanding"
    )):
        return "PLAN", "bright_magenta", "plan"

    # Thinking
    if any(w in lower for w in (
        "think", "thinking", "reason", "processing", "preparing",
        "generating", "generating content"
    )):
        return "THINK", "bright_cyan", "think"

    # Web
    if any(w in lower for w in ("search", "web", "internet")):
        return "WEB", "bright_blue", "tool"

    return "NOVA", "bright_cyan", "info"


def build_activity_panel(events, current_status, elapsed, event_count):
    table = Table(
        show_header=False,
        box=None,
        expand=True,
        padding=(0, 1),
    )

    table.add_column("time", width=9, no_wrap=True, style="dim")
    table.add_column("type", width=9, no_wrap=True)
    table.add_column("activity", ratio=1, overflow="ellipsis")

    visible = list(events)[-12:]

    for event in visible:
        kind = event.get("kind", "info")

        # Dim context rows, highlight verify/error
        if kind == "confirm":
            msg_style = "bright_green"
        elif kind == "error":
            msg_style = "bright_red"
        elif kind == "tool":
            msg_style = "white"
        elif kind == "verify":
            msg_style = "bright_cyan"
        else:
            msg_style = "dim"

        table.add_row(
            event["time"],
            Text(event["label"], style=f"bold {event['color']}"),
            Text(event["message"], style=msg_style, overflow="ellipsis"),
        )

    if not visible:
        table.add_row(
            "--:--:--",
            Text("IDLE", style="dim"),
            Text("Waiting for Nova...", style="dim"),
        )

    status = Text()
    status.append("● ", style="bright_cyan")
    status.append(current_status, style="bold white")

    footer = Text()
    footer.append(f"Events {event_count}", style="dim")
    footer.append("  ·  ", style="dim")
    footer.append(f"{elapsed:.1f}s", style="dim")

    return Panel(
        Group(status, Text(""), table, Text(""), footer),
        title="[bold bright_cyan]LIVE ACTIVITY[/bold bright_cyan]",
        border_style="bright_cyan",
        padding=(0, 1),
        expand=True,
    )


def render_verify_summary(events):
    """Show only the verification summary — no run trace."""
    confirmed = [e for e in events if e.get("kind") == "confirm"]
    failed    = [e for e in events if e.get("kind") == "error"
                 and e.get("label") in ("✗ FAIL", "ERROR")]

    if not confirmed and not failed:
        return

    vtable = Table(
        box=None,
        show_header=False,
        expand=True,
        padding=(0, 1),
    )
    vtable.add_column("icon",    width=4,  no_wrap=True)
    vtable.add_column("message", ratio=1)

    for e in confirmed:
        vtable.add_row(
            Text("✓", style="bold bright_green"),
            Text(e["message"], style="bright_green"),
        )
    for e in failed:
        vtable.add_row(
            Text("✗", style="bold bright_red"),
            Text(e["message"], style="bright_red"),
        )

    console.print(
        Panel(
            vtable,
            title="[bold bright_green]VERIFICATION[/bold bright_green]",
            border_style="bright_green",
            padding=(0, 1),
            expand=True,
        )
    )


def render_trace(events, elapsed):
    if not events:
        return

    # ── Full run trace ────────────────────────────────────────────────────────
    table = Table(
        box=box.SIMPLE,
        show_header=False,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("time", width=9,  no_wrap=True, style="dim")
    table.add_column("type", width=9,  no_wrap=True)
    table.add_column("event", ratio=1)

    for event in list(events)[-20:]:
        kind = event.get("kind", "info")
        if kind == "confirm":
            msg_style = "bright_green"
        elif kind == "error":
            msg_style = "bright_red"
        elif kind == "tool":
            msg_style = "white"
        elif kind == "verify":
            msg_style = "bright_cyan"
        else:
            msg_style = "dim"

        table.add_row(
            event["time"],
            Text(event["label"], style=f"bold {event['color']}"),
            Text(event["message"], style=msg_style),
        )

    title = Text()
    title.append("RUN TRACE", style="bold bright_cyan")
    title.append(f"  ·  {elapsed:.2f}s", style="dim")

    console.print(
        Panel(
            table,
            title=title,
            border_style="grey30",
            padding=(0, 1),
            expand=True,
        )
    )

    # ── Verification summary ──────────────────────────────────────────────────
    confirmed = [e for e in events if e.get("kind") == "confirm"]
    failed    = [e for e in events if e.get("kind") == "error"
                 and e.get("label") in ("✗ FAIL", "ERROR")]

    if not confirmed and not failed:
        return

    vtable = Table(
        box=None,
        show_header=False,
        expand=True,
        padding=(0, 1),
    )
    vtable.add_column("icon",    width=4,  no_wrap=True)
    vtable.add_column("message", ratio=1)

    for e in confirmed:
        vtable.add_row(
            Text("✓", style="bold bright_green"),
            Text(e["message"], style="bright_green"),
        )
    for e in failed:
        vtable.add_row(
            Text("✗", style="bold bright_red"),
            Text(e["message"], style="bright_red"),
        )

    console.print(
        Panel(
            vtable,
            title="[bold bright_green]VERIFICATION SUMMARY[/bold bright_green]",
            border_style="bright_green",
            padding=(0, 1),
            expand=True,
        )
    )


def run_agent(core: NovaCore, message: str, result: dict, state: dict):
    def on_status(status_message: str):
        status_message = str(status_message).strip()

        if not status_message:
            return

        label, color, kind = classify_status(status_message)
        state["current"] = status_message

        if status_message == state["last_status"]:
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


def ask(core: NovaCore, message: str):
    result = {}
    state = {
        "current": "Thinking...",
        "last_status": "",
        "events": deque(maxlen=50),
        "event_count": 0,
        "started": time.perf_counter(),
    }

    thread = threading.Thread(
        target=run_agent,
        args=(core, message, result, state),
        daemon=True,
    )
    thread.start()

    with Live(
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        while thread.is_alive():
            elapsed = time.perf_counter() - state["started"]
            live.update(
                build_activity_panel(
                    state["events"],
                    state["current"],
                    elapsed,
                    state["event_count"],
                )
            )
            time.sleep(0.08)

        elapsed = time.perf_counter() - state["started"]

        if "error" in result:
            error = str(result["error"])
            label, color, kind = classify_status(error)
            state["events"].append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "label": label,
                    "color": color,
                    "kind": "error",
                    "message": error,
                }
            )

            live.update(
                build_activity_panel(
                    state["events"],
                    "Request failed",
                    elapsed,
                    state["event_count"] + 1,
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
        time.sleep(0.2)

    return (
        result.get("response", "I couldn't generate a response."),
        elapsed,
        list(state["events"]),
    )


def toggle_access(core: NovaCore, name: str):
    access = core.get_access()
    new_value = not access[name]

    core.set_access(**{name: new_value})

    label = ACCESS_META[name][0]
    if new_value:
        console.print(
            f"[bright_green]● {label} enabled[/bright_green]"
        )
    else:
        console.print(
            f"[dim]○ {label} disabled[/dim]"
        )


def render_permissions(core: NovaCore):
    access = core.get_access()

    table = Table(
        title="Capability Controls",
        box=box.ROUNDED,
        border_style="bright_cyan",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Capability", style="bold white")
    table.add_column("State", justify="center")
    table.add_column("Controls", style="dim")

    for key in ("web", "git", "pc"):
        label, description = ACCESS_META[key]
        enabled = access[key]

        state = (
            Text("● ON", style="bold bright_green")
            if enabled
            else Text("○ OFF", style="dim")
        )

        table.add_row(
            label,
            state,
            description,
        )

    console.print(table)
    console.print(
        "[dim]Use /web, /git, or /pc to toggle a capability.[/dim]"
    )


def render_help():
    table = Table(
        title="Nova Controls",
        box=box.ROUNDED,
        border_style="bright_cyan",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Command", style="bright_cyan")
    table.add_column("Action", style="white")

    rows = [
        ("/web",         "Toggle web search access"),
        ("/git",         "Toggle Git / repository access"),
        ("/pc",          "Toggle terminal, files, desktop OS control"),
        ("/permissions", "Show current capability states"),
        ("/clear",       "Clear the screen, keep the session"),
        ("/reset",       "Start a fresh Nova session"),
        ("/help",        "Show this menu"),
        ("/exit",        "Exit Nova"),
    ]

    for command, action in rows:
        table.add_row(command, action)

    console.print(table)


def start_session():
    core = NovaCore()
    clear_screen()
    render_header(core)
    render_welcome()
    return core


def main():
    core = start_session()

    while True:
        try:
            console.print()
            message = Prompt.ask(
                "[bold bright_cyan]›[/bold bright_cyan]"
            ).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not message:
            continue

        command = message.lower()

        if command in {"exit", "quit", "/exit"}:
            break

        if command in {"/web", "/git", "/pc"}:
            toggle_access(core, command[1:])
            render_header(core)
            continue

        if command == "/permissions":
            render_permissions(core)
            continue

        if command == "/help":
            render_help()
            continue

        if command == "/clear":
            clear_screen()
            render_header(core)
            continue

        if command == "/reset":
            core = start_session()
            continue

        render_user(message)

        try:
            response, elapsed, events = ask(core, message)
            render_nova(response, elapsed)
            render_trace(events, elapsed)
        except KeyboardInterrupt:
            console.print(
                "\n[warning]Request interrupted.[/warning]"
            )
        except Exception as exc:
            console.print(
                Panel(
                    Text.from_markup(
                        "[bold red]Nova encountered an error[/bold red]\n\n"
                        f"{exc}"
                    ),
                    border_style="red",
                    padding=(0, 1),
                    expand=True,
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
