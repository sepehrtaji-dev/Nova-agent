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
from rich.control import Control, ControlType

from agent.core import NovaCore
from agent.introspection import inspect_model, runtime_profile
from utils.math_parser import format_response_math


# ── Theme ────────────────────────────────────────────────────────────────────

theme = Theme({
    "nova":       "bold #d97757",
    "user":       "bold white",
    "muted":      "dim",
    "accent":     "bright_blue",
    "success":    "bright_green",
    "warning":    "bright_yellow",
    "error":      "bright_red",
    "tool":       "bright_magenta",
    "info":       "bright_blue",
    "border":     "#d97757",
    "border_dim": "grey30",
    "surface":    "grey15",
    "highlight":  "reverse",
})

console = Console(theme=theme)


# ── Constants ────────────────────────────────────────────────────────────────

# Tool names are resolved from the live registry at runtime so newly
# registered tools can appear in activity traces without editing this UI.
TOOL_COLOR = "bright_magenta"

# Claude Code look: coral accent, grey chrome, amber mode line
CLAUDE = "#d97757"
USER_BG = "on #373737"
RULE_COLOR = "grey37"
MODE_COLOR = "#f5a623"

MASCOT = (
    " ▐▛███▜▌ ",
    "▝▜█████▛▘",
    "  ▘▘ ▝▝  ",
)

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
        return "CHECK", "#d97757", "verify"

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
        return "THINK", "#d97757", "think"

    if any(w in lower for w in ("search", "web", "internet")):
        return "WEB", "bright_blue", "tool"

    return "NOVA", "#d97757", "info"


# ── Layout Components ────────────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def clock_time() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def render_mascot() -> Text:
    body = f"on {CLAUDE}"
    art = Text()
    # row 1: head with two dark eyes
    art.append(" ")
    for cell in "BEBEB":
        if cell == "B":
            art.append(" ", style=body)
        else:
            art.append("▀", style=CLAUDE)  # solid top edge, dark eye below
    art.append(" ")
    art.append("\n")
    # row 2: wide body with arms
    art.append(" " * 7, style=body)
    art.append("\n")
    # row 3: four feet
    art.append("▀ ▀ ▀ ▀", style=CLAUDE)
    return art


def render_header(core: NovaCore) -> RenderableType:
    access = core.get_access()
    model_name = str(getattr(getattr(core, "brain", None), "model", "local")).strip()
    profile = runtime_profile(core)

    version = str(profile["version"]).lstrip("vV")
    info = Text()
    info.append("Nova", style="bold white")
    info.append(f" v{version}", style="dim")
    info.append("\n")
    info.append(f"{model_name} · {profile['provider']}", style="dim")
    info.append("\n")
    info.append(str(profile["working_directory"]), style="dim")

    banner = Table(box=None, show_header=False, expand=False, padding=(0, 3), pad_edge=False)
    banner.add_column("mascot", no_wrap=True)
    banner.add_column("info", no_wrap=True, overflow="ellipsis")
    banner.add_row(render_mascot(), info)

    # One status line, in the spot where Claude Code shows its notice line.
    status = Text()
    for index, key in enumerate(("web", "git", "pc")):
        if index:
            status.append("   ")
        status.append_text(access_pill(key, access[key]))
    status.append("  ·  ", style="dim")
    status.append(f"{profile['enabled_tools']}/{profile['registered_tools']} tools enabled", style="dim")
    status.append("  ·  ", style="dim")
    status.append(f"CTX {profile['context_budget']:,}", style="dim")
    status.append("  ·  ", style="dim")
    status.append("/help for commands", style="dim")

    return Group(banner, Text(""), status)


def render_welcome() -> RenderableType:
    return Text("")


def render_user(message: str) -> RenderableType:
    row = Table(box=None, show_header=False, expand=True, padding=(0, 1), pad_edge=False, collapse_padding=True)
    row.add_column("prompt", width=1, no_wrap=True)
    row.add_column("message", ratio=1)
    row.add_row(
        Text("❯", style="grey62"),
        Text(str(message), style="bold white"),
    )
    return Padding(row, (0, 0), style=USER_BG, expand=True)


def render_nova(message: str, elapsed: float | None = None) -> RenderableType:
    message = format_response_math(message)

    try:
        body = Markdown(message)
    except Exception:
        body = Text(str(message))

    row = Table(box=None, show_header=False, expand=True, padding=(0, 1), pad_edge=False, collapse_padding=True)
    row.add_column("bullet", width=1, no_wrap=True)
    row.add_column("body", ratio=1)
    row.add_row(Text("●", style="bold white"), body)

    if elapsed is None:
        return row

    thought = Text()
    thought.append("  Thought for ", style="grey62")
    thought.append(format_duration(elapsed), style="bold white")

    footer = Text()
    footer.append("✻ ", style="grey62")
    footer.append(f"Worked for {format_duration(elapsed)} · done {clock_time()}", style="grey62")

    return Group(thought, Text(""), row, Text(""), footer)


def build_activity_panel(
    events: deque,
    current_status: str,
    elapsed: float,
    event_count: int,
) -> RenderableType:
    glyphs = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]
    glyph = glyphs[int(elapsed * 8) % len(glyphs)]

    label = str(current_status).strip()
    if label.endswith("..."):
        label = label[:-3] + "…"

    status = Text()
    status.append(f"{glyph} ", style=CLAUDE)
    status.append(label, style=CLAUDE)

    meta = [format_duration(elapsed)]
    if event_count:
        meta.append(f"{event_count} event{'s' if event_count != 1 else ''}")
    if current_status not in ("Completed", "Request failed"):
        meta.append("ctrl+c to interrupt")
    status.append(f" ({' · '.join(meta)})", style="dim")

    visible = list(events)[-12:]
    if not visible:
        return status

    table = Table(
        show_header=False,
        box=None,
        expand=True,
        padding=(0, 1),
        pad_edge=False,
    )

    table.add_column("branch", width=4, no_wrap=True, style="dim")
    table.add_column("time", width=9, no_wrap=True, style="dim")
    table.add_column("type", width=9, no_wrap=True)
    table.add_column("activity", ratio=1, overflow="ellipsis")

    for index, event in enumerate(visible):
        kind = event.get("kind", "info")

        if kind == "confirm":
            msg_style = "bright_green"
        elif kind == "error":
            msg_style = "bright_red"
        elif kind == "tool":
            msg_style = "white"
        elif kind == "verify":
            msg_style = CLAUDE
        else:
            msg_style = "dim"

        table.add_row(
            "  ⎿" if index == 0 else "",
            event["time"],
            Text(event["label"], style=f"bold {event['color']}"),
            Text(event["message"], style=msg_style, overflow="ellipsis"),
        )

    return Group(status, table)


def render_verify_summary(events: deque) -> Optional[RenderableType]:
    confirmed = [e for e in events if e.get("kind") == "confirm"]
    failed = [e for e in events if e.get("kind") == "error"
              and e.get("label") in ("✗ FAIL", "ERROR")]

    if not confirmed and not failed:
        return None

    title = Text()
    title.append("● ", style="bold bright_green" if not failed else "bold bright_red")
    title.append("Verification", style="bold white")

    vtable = Table(
        box=None,
        show_header=False,
        expand=True,
        padding=(0, 1),
        pad_edge=False,
    )
    vtable.add_column("branch", width=4, no_wrap=True, style="dim")
    vtable.add_column("icon",   width=1,  no_wrap=True)
    vtable.add_column("message", ratio=1)

    first = True
    for e in confirmed:
        vtable.add_row(
            "  ⎿" if first else "",
            Text("✓", style="bold bright_green"),
            Text(e["message"], style="bright_green"),
        )
        first = False
    for e in failed:
        vtable.add_row(
            "  ⎿" if first else "",
            Text("✗", style="bold bright_red"),
            Text(e["message"], style="bright_red"),
        )
        first = False

    return Group(title, vtable)


# ── Input box (rule · ❯ prompt · rule · mode line) ──────────────────────────

def render_mode_line(core: NovaCore) -> RenderableType:
    access = core.get_access()
    state = " · ".join(
        f"{key} {'on' if access[key] else 'off'}" for key in ("web", "git", "pc")
    )
    line = Text()
    line.append("  ⏵⏵ ", style=MODE_COLOR)
    line.append(state, style=MODE_COLOR)
    line.append(" (/help for commands)", style="dim")
    return line


def _erase_input_box(lines_up: int, total: int = 4):
    """Wipe the 4-line input box (rule, prompt, rule, mode line) and park the
    cursor on its first line, so the next print starts where the box began."""
    console.control(Control.move_to_column(0))
    if lines_up:
        console.control(Control.move(0, -lines_up))
    for index in range(total):
        console.control(Control((ControlType.ERASE_IN_LINE, 2)))
        if index < total - 1:
            console.control(Control.move(0, 1))
    console.control(Control.move(0, -(total - 1)))
    console.control(Control.move_to_column(0))


class InputPrompt(Prompt):
    prompt_suffix = " "


def read_input(core: NovaCore) -> str:
    prompt = "[bold white]❯[/bold white]"
    interactive = console.is_terminal and not console.legacy_windows

    if not interactive:
        console.print()
        return InputPrompt.ask(prompt, console=console)

    # Draw the whole box first, then move the cursor back into it.
    console.print()
    console.print(Rule(style=RULE_COLOR))
    console.print()
    console.print(Rule(style=RULE_COLOR))
    console.print(render_mode_line(core))
    console.control(Control.move(0, -3))

    try:
        text = InputPrompt.ask(prompt, console=console)
    except (KeyboardInterrupt, EOFError):
        _erase_input_box(1)
        raise

    # Enter was pressed: the box turns into the message bar, like Claude Code.
    _erase_input_box(2)
    return text


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
            msg_style = "#d97757"
        else:
            msg_style = "dim"

        table.add_row(
            event["time"],
            Text(event["label"], style=f"bold {event['color']}"),
            Text(event["message"], style=msg_style),
        )

    title = Text()
    title.append("RUN TRACE", style="bold #d97757")
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
        border_style="#d97757",
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
        Text("Use /web, /git, or /pc to toggle a capability.", style="dim"),
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
    tools.add_column("Tool", style="#d97757")
    tools.add_column("Capability", style="dim")
    tools.add_column("Permission", justify="right")
    for item in profile["tools"]:
        enabled = Text("● ENABLED", style="bright_green") if item["enabled"] else Text("○ DISABLED", style="bright_yellow")
        tools.add_row(item["name"], item["capability"], enabled)
    if not profile["tools"]:
        tools.add_row("No tools registered", "—", "—")

    sections = [
        Panel(overview, title="[bold #d97757]RUNTIME IDENTITY[/bold #d97757]", border_style="#d97757", padding=(0, 1)),
        Panel(components, title="[bold #d97757]LIVE AGENT COMPONENTS[/bold #d97757]", border_style="grey30", padding=(0, 1)),
        Panel(tools, title="[bold #d97757]TOOL REGISTRY[/bold #d97757]", border_style="grey30", padding=(0, 1)),
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
    return Panel(table, title="[bold #d97757]NOVA RUNTIME STATUS[/bold #d97757]", border_style="#d97757", padding=(1, 2), expand=True)


def render_tool_registry(core: NovaCore) -> RenderableType:
    profile = runtime_profile(core)
    table = Table(title="Live Tool Registry", box=box.ROUNDED, border_style="#d97757", expand=True, padding=(0, 1))
    table.add_column("Tool", style="#d97757")
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
        border_style="#d97757",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Command", style="#d97757")
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
    text.append(f"{spinner} ", style="#d97757")
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
            message = read_input(core).strip()
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
            console.print("\n[warning]  ⎿  Interrupted · What should Nova do instead?[/warning]")
        except Exception as exc:
            err = Text()
            err.append("● ", style="bold bright_red")
            err.append("Nova encountered an error\n", style="bold bright_red")
            err.append(f"  ⎿  {exc}", style="bright_red")
            console.print(err)

    console.print()
    console.print(Text("Nova session ended.", style="dim"))


if __name__ == "__main__":
    from ui.launcher import main as launch_terminal_ui
    launch_terminal_ui()