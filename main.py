from __future__ import annotations

import os
import sys
import time
import signal
import threading
from collections import deque
from datetime import datetime
from typing import Optional

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.style import Style
from rich.segment import Segment
from rich.layout import Layout
from rich.columns import Columns
from rich.padding import Padding

from agent.core import NovaCore
from agent.introspection import inspect_model, runtime_profile
from utils.math_parser import format_response_math


# ── Theme ────────────────────────────────────────────────────────────────────

theme = Theme({
    "nova":       "bold bright_cyan",
    "user":       "bold white",
    "muted":      "dim",
    "accent":     "bright_blue",
    "success":    "bright_green",
    "warning":    "bright_yellow",
    "error":      "bright_red",
    "tool":       "bright_magenta",
    "info":       "bright_blue",
    "border":     "bright_cyan",
    "border_dim": "grey30",
    "surface":    "grey15",
    "highlight":  "reverse",
})

console = Console(theme=theme)


# ── Constants ────────────────────────────────────────────────────────────────

# Tool names are resolved from the live registry at runtime so newly
# registered tools can appear in activity traces without editing this UI.
TOOL_COLOR = "bright_magenta"

ACCESS_META = {
    "web": ("WEB SEARCH",  "Web search access"),
    "git": ("GIT",         "Repository operations"),
    "pc":  ("PC USE",      "Terminal · Files · Desktop OS control"),
}

WELCOME_ART = r"""
  _   _  _____  __     ___
 | \ | ||  __ \ \ \   / / |
 |  \| || |  | | \ \_/ /| |
 | . ` || |  | |  \   / | |
 | |\  || |__| |   | |  | |____
 |_| \_||_____/    |_|  |______|
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def terminal_width() -> int:
    return max(78, min(console.width, 132))


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


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


def classify_status(message: str, tool_names=None) -> tuple[str, str, str]:
    text = str(message).strip()
    lower = text.lower()

    if text.startswith("✓"):
        return "✓ OK",  "bright_green",  "confirm"
    if text.startswith("✗"):
        return "✗ FAIL", "bright_red",   "error"

    if tool_names:
        # Longest-first avoids matching a short tool name inside a longer one.
        for tool_name in sorted(tool_names, key=len, reverse=True):
            normalized = str(tool_name).strip().lower()
            if normalized and normalized in lower:
                label = normalized.upper()
                if label == "WEB_SEARCH":
                    label = "WEB"
                elif label == "TERMINAL":
                    label = "TERM"
                elif label == "CREATE_DIRECTORY":
                    label = "MKDIR"
                elif label.endswith("_FILE"):
                    label = label.removesuffix("_FILE")
                return label[:12], TOOL_COLOR, "tool"

    if any(w in lower for w in (
        "error", "failed", "failure", "exception", "blocked",
        "invalid", "rejected", "denied"
    )):
        return "ERROR", "bright_red", "error"

    if any(w in lower for w in ("verif", "confirm", "checking")):
        return "CHECK", "bright_cyan", "verify"

    if any(w in lower for w in (
        "success", "completed", "complete", "done", "finished"
    )):
        return "DONE", "bright_green", "success"

    if any(w in lower for w in (
        "plan", "planning", "replan", "deciding", "understanding"
    )):
        return "PLAN", "bright_magenta", "plan"

    if any(w in lower for w in (
        "think", "thinking", "reason", "processing", "preparing",
        "generating", "generating content"
    )):
        return "THINK", "bright_cyan", "think"

    if any(w in lower for w in ("search", "web", "internet")):
        return "WEB", "bright_blue", "tool"

    return "NOVA", "bright_cyan", "info"


# ── Layout Components ────────────────────────────────────────────────────────

def render_header(core: NovaCore) -> RenderableType:
    access = core.get_access()
    model_name = str(getattr(getattr(core, "brain", None), "model", "local")).strip()

    # Top bar
    top = Table(box=None, show_header=False, expand=True, padding=(0, 1))
    top.add_column("brand", ratio=1, no_wrap=True)
    top.add_column("mode", justify="center", no_wrap=True)
    top.add_column("model", justify="right", no_wrap=True)

    brand = Text()
    brand.append("✦ ", style="bright_cyan")
    brand.append("NOVA", style="bold white")
    brand.append("  ", style="white")
    brand.append("LOCAL AI AGENT", style="dim")

    top.add_row(
        brand,
        Text("CHAT / AGENT", style="dim"),
        Text(model_name.upper(), style="dim"),
    )

    # Permissions bar
    perms = Table(box=None, show_header=False, expand=True, padding=(0, 1))
    perms.add_column("web", ratio=1, no_wrap=True)
    perms.add_column("git", ratio=1, justify="center", no_wrap=True)
    perms.add_column("pc", ratio=1, justify="right", no_wrap=True)

    perms.add_row(
        access_pill("web", access["web"]),
        access_pill("git", access["git"]),
        access_pill("pc", access["pc"]),
    )

    # Runtime strip is derived from the live registry and config, without a network probe.
    profile = runtime_profile(core)
    runtime = Text()
    runtime.append(f"  {profile['enabled_tools']}/{profile['registered_tools']} tools enabled", style="bold bright_green")
    runtime.append("   ·   ", style="dim")
    runtime.append(f"CTX {profile['context_budget']:,}", style="bright_cyan")
    runtime.append("   ·   ", style="dim")
    runtime.append(f"PY {profile['python']}", style="dim")

    # Command hint bar
    hint = Text()
    hint.append("  /self", style="bright_cyan")
    hint.append(" inspect   ", style="dim")
    hint.append("/model", style="bright_blue")
    hint.append(" metadata   ", style="dim")
    hint.append("/doctor", style="bright_yellow")
    hint.append(" diagnostics   ", style="dim")
    hint.append("/help", style="white")

    return Panel(
        Group(top, perms, runtime, hint),
        border_style="bright_cyan",
        padding=(0, 0),
        expand=True,
    )


def render_welcome() -> RenderableType:
    content = Text()
    content.append(WELCOME_ART, style="bright_cyan")
    content.append("\n\n")
    content.append("Nova is ready.\n", style="bold white")
    content.append(
        "Ask naturally. Nova can plan tasks, use enabled tools, "
        "inspect real results, re-plan, and finish the work.\n\n",
        style="dim",
    )
    content.append(" /self ", style="bright_cyan")
    content.append("runtime profile   ", style="dim")
    content.append("/model ", style="bright_blue")
    content.append("model metadata   ", style="dim")
    content.append("/doctor ", style="bright_yellow")
    content.append("health checks\n\n", style="dim")
    content.append(
        "Nova reports observed facts and metadata, not guessed capabilities or private model reasoning.",
        style="dim italic",
    )

    return Panel(
        content,
        title="[bold bright_cyan]SESSION[/bold bright_cyan]",
        border_style="grey30",
        padding=(1, 2),
        expand=True,
    )


def render_user(message: str) -> RenderableType:
    label = Text()
    label.append("YOU", style="bold white")
    label.append("  ·  MESSAGE", style="dim")

    return Group(
        label,
        Panel(
            message,
            border_style="grey37",
            padding=(0, 1),
            expand=True,
        ),
    )


def render_nova(message: str, elapsed: float | None = None) -> RenderableType:
    label = Text()
    label.append("NOVA", style="bold bright_cyan")

    if elapsed is not None:
        label.append(f"  ·  {elapsed:.2f}s", style="dim")

    message = format_response_math(message)

    try:
        body = Markdown(message)
    except Exception:
        body = Text(str(message))

    return Group(
        label,
        Panel(
            body,
            border_style="bright_cyan",
            padding=(0, 1),
            expand=True,
        ),
    )


def build_activity_panel(
    events: deque,
    current_status: str,
    elapsed: float,
    event_count: int,
) -> RenderableType:
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


def render_verify_summary(events: deque) -> Optional[RenderableType]:
    confirmed = [e for e in events if e.get("kind") == "confirm"]
    failed = [e for e in events if e.get("kind") == "error"
              and e.get("label") in ("✗ FAIL", "ERROR")]

    if not confirmed and not failed:
        return None

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

    return Panel(
        vtable,
        title="[bold bright_green]VERIFICATION[/bold bright_green]",
        border_style="bright_green",
        padding=(0, 1),
        expand=True,
    )


def render_trace(events: deque, elapsed: float) -> Optional[RenderableType]:
    if not events:
        return None

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

    return Panel(
        table,
        title=title,
        border_style="grey30",
        padding=(0, 1),
        expand=True,
    )


def render_permissions(core: NovaCore) -> RenderableType:
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

        table.add_row(label, state, description)

    return Group(
        table,
        Text(""),
        Text("[dim]Use /web, /git, or /pc to toggle a capability.[/dim]", style="dim"),
    )


def render_runtime_profile(core: NovaCore, include_model: bool = True) -> RenderableType:
    profile = runtime_profile(core)

    overview = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    overview.add_column("field", style="dim", width=22)
    overview.add_column("value", style="white", ratio=1)
    overview.add_row("Identity", f"{profile['identity']} · {profile['developer']}")
    overview.add_row("Version", profile["version"])
    overview.add_row("Provider / model", f"{profile['provider']} · {profile['configured_model']}")
    overview.add_row("Python runtime", f"{profile['implementation']} {profile['python']} · {profile['system']}")
    overview.add_row("Platform", profile["platform"])
    overview.add_row("Working directory", profile["working_directory"])
    overview.add_row("Agent budgets", f"Context {profile['context_budget']:,} · Output {profile['output_budget']:,}")
    overview.add_row("Tool registry", f"{profile['enabled_tools']}/{profile['registered_tools']} enabled")
    overview.add_row("Core components", f"{profile['present_components']}/{profile['component_count']} present")
    overview.add_row("Execution ledger", "available" if profile["execution_state_available"] else "missing")

    components = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
    components.add_column("Component", style="white")
    components.add_column("Implementation", style="dim")
    components.add_column("State", justify="right")
    for item in profile["components"]:
        state = Text("● PRESENT", style="bright_green") if item["present"] else Text("○ MISSING", style="bright_red")
        components.add_row(item["label"], item["implementation"], state)

    tools = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
    tools.add_column("Tool", style="bright_cyan")
    tools.add_column("Capability", style="dim")
    tools.add_column("Permission", justify="right")
    for item in profile["tools"]:
        enabled = Text("● ENABLED", style="bright_green") if item["enabled"] else Text("○ DISABLED", style="bright_yellow")
        tools.add_row(item["name"], item["capability"], enabled)
    if not profile["tools"]:
        tools.add_row("No tools registered", "—", "—")

    sections = [
        Panel(overview, title="[bold bright_cyan]RUNTIME IDENTITY[/bold bright_cyan]", border_style="bright_cyan", padding=(0, 1)),
        Panel(components, title="[bold bright_cyan]LIVE AGENT COMPONENTS[/bold bright_cyan]", border_style="grey30", padding=(0, 1)),
        Panel(tools, title="[bold bright_cyan]TOOL REGISTRY[/bold bright_cyan]", border_style="grey30", padding=(0, 1)),
    ]

    if include_model:
        model = inspect_model(core)
        model_table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
        model_table.add_column("field", style="dim", width=22)
        model_table.add_column("value", style="white", ratio=1)
        model_table.add_row("Metadata status", model["status"])
        model_table.add_row("Configured tag", model["configured_name"])
        model_table.add_row("Parameter count", model["parameter_count"])
        model_table.add_row("Reported size", model["parameter_size"])
        model_table.add_row("Architecture", model["architecture"])
        model_table.add_row("Quantization", model["quantization"])
        model_table.add_row("Model context length", model["model_context_length"])
        model_table.add_row("Capabilities", ", ".join(model["capabilities"]) or "Unknown")
        model_table.add_row("Evidence", model["detail"])
        sections.append(Panel(model_table, title="[bold bright_blue]OLLAMA MODEL METADATA[/bold bright_blue]", border_style="bright_blue", padding=(0, 1)))
        sections.append(Text("Parameter count comes from Ollama metadata; unknown values are not guessed. Metadata availability does not prove text generation works.", style="dim italic"))

    return Group(*sections)


def render_model_profile(core: NovaCore) -> RenderableType:
    model = inspect_model(core)
    table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    table.add_column("field", style="dim", width=22)
    table.add_column("value", style="white", ratio=1)
    table.add_row("Status", model["status"])
    table.add_row("Configured model", model["configured_name"])
    table.add_row("Parameter count", model["parameter_count"])
    table.add_row("Reported parameter size", model["parameter_size"])
    table.add_row("Architecture", model["architecture"])
    table.add_row("Quantization", model["quantization"])
    table.add_row("Context length", model["model_context_length"])
    table.add_row("Capabilities", ", ".join(model["capabilities"]) or "Unknown")
    table.add_row("Metadata", model["detail"])
    return Panel(table, title="[bold bright_blue]OLLAMA MODEL INSPECTOR[/bold bright_blue]", border_style="bright_blue", padding=(1, 2), expand=True)


def render_runtime_status(core: NovaCore) -> RenderableType:
    profile = runtime_profile(core)
    table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    table.add_column("field", style="dim", width=22)
    table.add_column("value", style="white", ratio=1)
    table.add_row("Nova", f"{profile['identity']} · version {profile['version']}")
    table.add_row("Model", profile["configured_model"])
    table.add_row("Runtime", f"Python {profile['python']} · {profile['platform']}")
    table.add_row("Tools", f"{profile['enabled_tools']}/{profile['registered_tools']} enabled")
    table.add_row("Components", f"{profile['present_components']}/{profile['component_count']} present")
    table.add_row("Context / output", f"{profile['context_budget']:,} / {profile['output_budget']:,} tokens configured")
    table.add_row("Permissions", ", ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in profile["access"].items()))
    return Panel(table, title="[bold bright_cyan]NOVA RUNTIME STATUS[/bold bright_cyan]", border_style="bright_cyan", padding=(1, 2), expand=True)


def render_tool_registry(core: NovaCore) -> RenderableType:
    profile = runtime_profile(core)
    table = Table(title="Live Tool Registry", box=box.ROUNDED, border_style="bright_cyan", expand=True, padding=(0, 1))
    table.add_column("Tool", style="bright_cyan")
    table.add_column("Capability", style="dim")
    table.add_column("State", justify="center")
    table.add_column("Description", overflow="ellipsis")
    for item in profile["tools"]:
        state = Text("ENABLED", style="bright_green") if item["enabled"] else Text("DISABLED", style="bright_yellow")
        table.add_row(item["name"], item["capability"], state, item["description"] or "—")
    if not profile["tools"]:
        table.add_row("—", "—", "—", "No tools are registered.")
    return table


def render_doctor(core: NovaCore) -> RenderableType:
    report = core.diagnostics.snapshot(core, probe_model=True)
    table = Table(box=box.SIMPLE, expand=True, padding=(0, 1))
    table.add_column("Check", style="white")
    table.add_column("State", justify="center")
    table.add_column("Evidence", ratio=1)
    for item in report["checks"]:
        status = item["status"]
        color = "bright_green" if status in {"available", "configured"} else ("bright_red" if status == "failed" else "bright_yellow")
        table.add_row(item["name"], Text(status.upper(), style=f"bold {color}"), item["detail"])
    summary = report["summary"]
    footer = Text(
        f"Tools: {summary['registered_tools']} registered · {summary['verified_tools']} recently verified · "
        f"{summary['failed_tools']} failed last check · {summary['untested_tools']} untested · {summary['disabled_tools']} disabled",
        style="dim",
    )
    return Panel(Group(table, Text(""), footer), title="[bold bright_yellow]NOVA SELF-DIAGNOSTICS[/bold bright_yellow]", border_style="bright_yellow", padding=(1, 2), expand=True)


def render_help() -> RenderableType:
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
        ("/self",        "Inspect Nova's live runtime, components, tools and model metadata"),
        ("/model",       "Query Ollama for model parameters, architecture and quantization"),
        ("/tools",       "List registered tools and permission state"),
        ("/doctor",      "Run local configuration and Ollama diagnostics"),
        ("/status",      "Show a fast runtime summary without probing Ollama"),
        ("/clear",       "Clear the screen, keep the session"),
        ("/reset",       "Start a fresh Nova session"),
        ("/help",        "Show this menu"),
        ("/exit",        "Exit Nova"),
    ]

    for command, action in rows:
        table.add_row(command, action)

    return table


def render_spinner(status: str, frame: int) -> Text:
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner = frames[frame % len(frames)]
    text = Text()
    text.append(f"{spinner} ", style="bright_cyan")
    text.append(status, style="bold white")
    return text


# ── Agent Runner ─────────────────────────────────────────────────────────────

def run_agent(
    core: NovaCore,
    message: str,
    result: dict,
    state: dict,
):
    def on_status(status_message: str):
        status_message = str(status_message).strip()
        if not status_message:
            return

        label, color, kind = classify_status(status_message, getattr(getattr(core, "tools", None), "tools", {}).keys())
        state["current"] = status_message

        if status_message == state["last_status"]:
            return

        state["last_status"] = status_message
        state["events"].append({
            "time": now(),
            "label": label,
            "color": color,
            "kind": kind,
            "message": status_message,
        })
        state["event_count"] += 1

    core.status_callback = on_status

    try:
        result["response"] = core.ask(message)
    except Exception as exc:
        result["error"] = exc


def ask(
    core: NovaCore,
    message: str,
) -> tuple[str, float, list]:
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

    frame = 0
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
            frame += 1
            time.sleep(0.08)

        elapsed = time.perf_counter() - state["started"]

        if "error" in result:
            error = str(result["error"])
            label, color, kind = classify_status(error, getattr(getattr(core, "tools", None), "tools", {}).keys())
            state["events"].append({
                "time": now(),
                "label": label,
                "color": color,
                "kind": "error",
                "message": error,
            })

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


# ── Commands ─────────────────────────────────────────────────────────────────

def toggle_access(core: NovaCore, name: str):
    access = core.get_access()
    new_value = not access[name]
    core.set_access(**{name: new_value})

    label = ACCESS_META[name][0]
    if new_value:
        console.print(f"[bright_green]● {label} enabled[/bright_green]")
    else:
        console.print(f"[dim]○ {label} disabled[/dim]")


# ── Session ──────────────────────────────────────────────────────────────────

def start_session() -> NovaCore:
    core = NovaCore()
    clear_screen()
    console.print(render_header(core))
    console.print()
    console.print(render_welcome())
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
            console.print()
            console.print(render_header(core))
            continue

        if command == "/permissions":
            console.print()
            console.print(render_permissions(core))
            continue

        if command in {"/self", "/introspect"}:
            console.print()
            console.print(render_runtime_profile(core, include_model=True))
            continue

        if command == "/model":
            console.print()
            console.print(render_model_profile(core))
            continue

        if command == "/status":
            console.print()
            console.print(render_runtime_status(core))
            continue

        if command == "/tools":
            console.print()
            console.print(render_tool_registry(core))
            continue

        if command in {"/doctor", "/diagnostics"}:
            console.print()
            console.print(render_doctor(core))
            continue

        if command == "/help":
            console.print()
            console.print(render_help())
            continue

        if command == "/clear":
            clear_screen()
            console.print(render_header(core))
            continue

        if command == "/reset":
            core = start_session()
            continue

        console.print()
        console.print(render_user(message))

        try:
            response, elapsed, events = ask(core, message)
            console.print()
            console.print(render_nova(response, elapsed))

            verify = render_verify_summary(events)
            if verify:
                console.print()
                console.print(verify)

        except KeyboardInterrupt:
            console.print("\n[warning]Request interrupted.[/warning]")
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
    from ui.launcher import main as launch_terminal_ui
    launch_terminal_ui()
