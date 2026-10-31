"""Textual full-screen terminal interface for Nova (Claude Code style)."""
from __future__ import annotations

from collections import deque
from datetime import datetime
from time import perf_counter

from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, RichLog, Static

from agent.core import NovaCore
from agent.introspection import inspect_model, runtime_profile

try:  # reuse the same activity labels as the Rich interface when available
    from main import classify_status
except Exception:  # pragma: no cover - the UI must not depend on it
    classify_status = None


# ── Claude Code look ─────────────────────────────────────────────────────────

CLAUDE = "#d97757"
BG = "#0c0c0c"
USER_BG = "on #373737"
RULE_COLOR = "grey37"
MODE_COLOR = "#f5a623"
GREY = "grey62"
SPINNER = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]


def _duration(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _clock() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def _mascot() -> Text:
    body = f"on {CLAUDE}"
    art = Text()
    art.append(" ")
    for cell in "BEBEB":
        if cell == "B":
            art.append(" ", style=body)
        else:
            art.append("▀", style=CLAUDE)  # solid top edge, dark eye below
    art.append(" ")
    art.append("\n")
    art.append(" " * 7, style=body)
    art.append("\n")
    art.append("▀ ▀ ▀ ▀", style=CLAUDE)
    return art


def _user_bar(message: str):
    row = Table(box=None, show_header=False, expand=True, padding=(0, 1), pad_edge=False, collapse_padding=True)
    row.add_column("prompt", width=1, no_wrap=True)
    row.add_column("message", ratio=1)
    row.add_row(Text("❯", style=GREY), Text(str(message), style="bold white"))
    return Padding(row, (0, 0), style=USER_BG, expand=True)


def _reply(response: str, elapsed: float):
    row = Table(box=None, show_header=False, expand=True, padding=(0, 1), pad_edge=False, collapse_padding=True)
    row.add_column("bullet", width=1, no_wrap=True)
    row.add_column("body", ratio=1)
    row.add_row(Text("●", style="bold white"), Markdown(response))

    thought = Text()
    thought.append("  Thought for ", style=GREY)
    thought.append(_duration(elapsed), style="bold white")

    footer = Text()
    footer.append("✻ ", style=GREY)
    footer.append(f"Worked for {_duration(elapsed)} · done {_clock()}", style=GREY)

    return Group(thought, Text(""), row, Text(""), footer)


def _error(message: str) -> Text:
    text = Text()
    text.append("● ", style="bold bright_red")
    text.append("Request failed\n", style="bold bright_red")
    text.append(f"  ⎿  {message}", style="bright_red")
    return text


def _panel(body, title: str, border: str = CLAUDE) -> Panel:
    border = CLAUDE if border == "cyan" else border
    return Panel(
        body,
        title=Text(title, style=f"bold {border}"),
        title_align="left",
        border_style=border,
        padding=(0, 1),
    )


class NovaTextualApp(App):
    """Full-screen chat UI. Agent execution runs in a worker, not the UI loop."""

    TITLE = "NOVA · Local AI Agent"
    SUB_TITLE = "Textual interface · Ollama runtime"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #0c0c0c; color: #cccccc; layout: vertical; }

    #transcript {
        height: 1fr;
        background: #0c0c0c;
        border: none;
        padding: 0;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        scrollbar-background: #0c0c0c;
        scrollbar-background-hover: #0c0c0c;
        scrollbar-background-active: #0c0c0c;
        scrollbar-color: #262626;
        scrollbar-color-hover: #3a3a3a;
        scrollbar-color-active: #4a4a4a;
        scrollbar-corner-color: #0c0c0c;
    }

    #activity { height: auto; padding: 0; background: #0c0c0c; }

    .rule { height: 1; background: #0c0c0c; }
    #inputrow { height: 1; background: #0c0c0c; }
    #chevron { width: 2; height: 1; color: #cccccc; background: #0c0c0c; padding: 0; }
    #prompt, #prompt:focus, #prompt:disabled {
        height: 1;
        border: none;
        padding: 0;
        background: #0c0c0c;
        background-tint: transparent;
        color: #ffffff;
    }
    #prompt:disabled { color: #8a8a8a; }
    #modeline { height: 1; padding: 0; background: #0c0c0c; }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.core: NovaCore | None = None
        self.started_at = perf_counter()
        self.busy = False
        self._busy_started = perf_counter()
        self._status = ""
        self._notice = ""
        self._events: deque = deque(maxlen=50)
        self._last_event = ""

    def compose(self) -> ComposeResult:
        yield RichLog(id="transcript", wrap=True, markup=False, auto_scroll=True, min_width=20)
        yield Static("", id="activity")
        yield Static(Rule(style=RULE_COLOR), classes="rule")
        with Horizontal(id="inputrow"):
            yield Static("❯", id="chevron")
            yield Input(placeholder="", id="prompt")
        yield Static(Rule(style=RULE_COLOR), classes="rule")
        yield Static("", id="modeline")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)
        self._refresh_activity()
        self.query_one("#prompt", Input).focus()
        try:
            self.core = NovaCore(status_callback=self._status_from_core)
            self._write_banner()
            self._refresh_sidebar()
            self._set_status("Ready · local Ollama agent")
        except Exception as exc:
            self.query_one("#transcript", RichLog).write(
                _panel(f"{type(exc).__name__}: {exc}", "Startup error", "red")
            )
            self._set_status("Startup failed")

    # ── Rendering helpers ────────────────────────────────────────────────────

    def _write_banner(self) -> None:
        if self.core is None:
            return
        profile = runtime_profile(self.core)
        access = self.core.get_access()

        version = str(profile["version"]).lstrip("vV")
        info = Text()
        info.append("Nova", style="bold white")
        info.append(f" v{version}", style="dim")
        info.append("\n")
        info.append(f"{profile['configured_model']} · {profile['provider']}", style="dim")
        info.append("\n")
        info.append(str(profile["working_directory"]), style="dim")

        banner = Table(box=None, show_header=False, expand=False, padding=(0, 3), pad_edge=False)
        banner.add_column("mascot", no_wrap=True)
        banner.add_column("info", no_wrap=True, overflow="ellipsis")
        banner.add_row(_mascot(), info)

        status = Text()
        for index, key in enumerate(("web", "git", "pc")):
            if index:
                status.append("   ")
            if access.get(key, True):
                status.append("● ", style="bright_green")
                status.append(key.upper() if key != "web" else "WEB SEARCH", style="bold bright_green")
            else:
                status.append("○ ", style="dim")
                status.append(key.upper() if key != "web" else "WEB SEARCH", style="dim")
        status.append("  ·  ", style="dim")
        status.append(f"{profile['enabled_tools']}/{profile['registered_tools']} tools enabled", style="dim")
        status.append("  ·  ", style="dim")
        status.append(f"CTX {profile['context_budget']:,}", style="dim")

        log = self.query_one("#transcript", RichLog)
        log.write(banner)
        log.write(Text(""))
        log.write(status)

    def _refresh_sidebar(self) -> None:
        """Refresh the amber mode line under the input box (permissions)."""
        line = Text()
        if self.core is None:
            line.append("  ⏵⏵ starting…", style=MODE_COLOR)
        else:
            access = self.core.get_access()
            state = " · ".join(f"{key} {'on' if access.get(key, True) else 'off'}" for key in ("web", "git", "pc"))
            line.append("  ⏵⏵ ", style=MODE_COLOR)
            line.append(state, style=MODE_COLOR)
            line.append(" (/help for commands)", style="dim")
        self.query_one("#modeline", Static).update(line)

    def _render_activity(self):
        if self.busy:
            elapsed = perf_counter() - self._busy_started
            glyph = SPINNER[int(elapsed * 8) % len(SPINNER)]
            label = (self._status or "Working…").strip()
            if label.endswith("..."):
                label = label[:-3] + "…"

            head = Text()
            head.append(f"{glyph} ", style=CLAUDE)
            head.append(label, style=CLAUDE)
            meta = [_duration(elapsed)]
            if self._events:
                meta.append(f"{len(self._events)} event{'s' if len(self._events) != 1 else ''}")
            head.append(f" ({' · '.join(meta)})", style="dim")

            visible = list(self._events)[-8:]
            if not visible:
                return head

            table = Table(show_header=False, box=None, expand=True, padding=(0, 1), pad_edge=False)
            table.add_column("branch", width=4, no_wrap=True, style="dim")
            table.add_column("time", width=9, no_wrap=True, style="dim")
            table.add_column("type", width=9, no_wrap=True)
            table.add_column("activity", ratio=1, overflow="ellipsis")
            for index, event in enumerate(visible):
                kind = event["kind"]
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
            return Group(head, table)

        if self._notice:
            return Text(f"  ⎿  {self._notice}", style="dim")
        return None

    def _refresh_activity(self) -> None:
        widget = self.query_one("#activity", Static)
        content = self._render_activity()
        widget.display = content is not None
        if content is not None:
            widget.update(content)

    def _tick(self) -> None:
        if self.busy:
            self._refresh_activity()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = busy
        if busy:
            self._busy_started = perf_counter()
            self._events.clear()
            self._last_event = ""
            self._notice = ""
        else:
            prompt.focus()

    def _set_status(self, message: str) -> None:
        self._status = message
        if not self.busy:
            self._notice = "" if message.startswith(("Ready", "New Nova session ready")) else message
        self._refresh_activity()

    def _status_from_core(self, message: str) -> None:
        try:
            self.call_from_thread(self._record_activity, str(message))
        except Exception:
            # The app may already be closing; status reporting must not break the agent.
            pass

    def _record_activity(self, message: str) -> None:
        message = message.strip()
        if message and message != self._last_event:
            self._last_event = message
            label, color, kind = "NOVA", "bright_cyan", "info"
            if classify_status is not None:
                try:
                    tool_names = getattr(getattr(self.core, "tools", None), "tools", {}).keys()
                    label, color, kind = classify_status(message, tool_names)
                except Exception:
                    pass
            self._events.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "label": label,
                "color": color,
                "kind": kind,
                "message": message,
            })
        self._set_status(message[:180])

    # ── Input handling ───────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message or self.busy:
            return
        event.input.value = ""
        self._notice = ""
        self._refresh_activity()
        if message.startswith("/"):
            self._handle_command(message)
            return
        log = self.query_one("#transcript", RichLog)
        log.write(Text(""))
        log.write(_user_bar(message), expand=True)
        self._set_busy(True)
        self._set_status("Nova is working…")
        self.run_worker(lambda: self._process_request(message), thread=True, exclusive=True)

    def _process_request(self, message: str) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        started = perf_counter()
        try:
            response = self.core.ask(message)
            elapsed = perf_counter() - started
            self.call_from_thread(self._finish_response, str(response), elapsed)
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_response(self, response: str, elapsed: float) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text(""))
        log.write(_reply(response, elapsed), expand=True)
        self._set_busy(False)
        self._set_status(f"Ready · last response {elapsed:.2f}s")

    def _finish_error(self, message: str) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text(""))
        log.write(_error(message))
        self._set_busy(False)
        self._set_status("Request failed")

    def _handle_command(self, command: str) -> None:
        if self.core is None:
            self._set_status("Nova core is not initialized")
            return
        log = self.query_one("#transcript", RichLog)
        name = command.split(maxsplit=1)[0].lower()
        if name in {"/exit", "/quit"}:
            self.exit()
        elif name in {"/help", "/?"}:
            log.write(Text(""))
            log.write(_panel(
                "/self  runtime + Ollama metadata\n/model  model metadata\n/status  local status\n"
                "/tools  tool registry\n/permissions  capability toggles\n/web, /git, /pc  toggle access\n"
                "/doctor  local health diagnostics\n/memory  list saved long-term memory\n"
                "/forget <category> <key>  remove one saved memory\n"
                "/clear  clear conversation\n/reset  restart core\n/exit  quit",
                "COMMANDS"))
        elif name == "/memory":
            entries = self.core.long_memory.entries()
            lines = [f"{item['key']}: {item['value']}" for item in entries]
            body = "\n".join(lines) if lines else "No saved long-term memories."
            log.write(Text(""))
            log.write(_panel(body, f"SAVED MEMORY · {len(entries)} entries"))
        elif name == "/forget":
            parts = command.split(maxsplit=2)
            log.write(Text(""))
            if len(parts) != 3:
                log.write(_panel(
                    "Usage: /forget <category> <key>\nExample: /forget profile gpu",
                    "MEMORY COMMAND", "yellow"))
            elif self.core.long_memory.forget(parts[1], parts[2]):
                log.write(_panel(
                    f"Forgot {parts[1]}.{parts[2]}.", "MEMORY UPDATED", "green"))
            else:
                log.write(_panel(
                    f"No saved memory found for {parts[1]}.{parts[2]}.",
                    "MEMORY NOT FOUND", "yellow"))
        elif name == "/clear":
            self._clear_transcript()
        elif name == "/status":
            profile = runtime_profile(self.core)
            log.write(Text(""))
            log.write(_panel(
                f"Model: {profile['configured_model']}\nPython: {profile['python']}\n"
                f"Tools: {profile['enabled_tools']}/{profile['registered_tools']}\n"
                f"Components: {profile['present_components']}/{profile['component_count']}\n"
                "This status snapshot does not contact Ollama.",
                "STATUS"))
        elif name in {"/self", "/model"}:
            self._set_busy(True)
            self._set_status("Reading local Ollama metadata…")
            self.run_worker(lambda: self._inspect(name), thread=True, exclusive=True)
        elif name == "/doctor":
            self._set_busy(True)
            self._set_status("Running local diagnostics…")
            self.run_worker(self._diagnose, thread=True, exclusive=True)
        elif name == "/tools":
            profile = runtime_profile(self.core)
            table = Table(title="Tool registry", expand=True, border_style=RULE_COLOR, title_style=f"bold {CLAUDE}")
            table.add_column("Tool")
            table.add_column("Capability")
            table.add_column("Permission")
            for tool in profile["tools"]:
                table.add_row(tool["name"], tool["capability"], "ON" if tool["enabled"] else "OFF")
            log.write(Text(""))
            log.write(table)
        elif name == "/permissions":
            profile = runtime_profile(self.core)
            log.write(Text(""))
            log.write(_panel(
                "\n".join(f"{key}: {'ON' if enabled else 'OFF'}" for key, enabled in profile["access"].items()),
                "PERMISSIONS"))
        elif name in {"/web", "/git", "/pc"}:
            key = name[1:]
            current = self.core.get_access().get(key, True)
            self.core.set_access(**{key: not current})
            self._refresh_sidebar()
            self._set_status(f"{key.upper()} access {'enabled' if not current else 'disabled'}")
        elif name == "/reset":
            self._set_busy(True)
            self.run_worker(self._reset_core, thread=True, exclusive=True)
        else:
            self._set_status(f"Unknown command: {name} · try /help")

    def _clear_transcript(self) -> None:
        self.query_one("#transcript", RichLog).clear()
        self._write_banner()

    def _diagnose(self) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        try:
            report = self.core.diagnostics.snapshot(self.core, probe_model=True)
            lines = [
                f"{item['name']}: {item['status']} — {item['detail']}"
                for item in report["checks"]
            ]
            summary = report["summary"]
            lines.append(
                f"Tools: {summary['registered_tools']} registered · "
                f"{summary['verified_tools']} recently verified · "
                f"{summary['failed_tools']} failed · "
                f"{summary['untested_tools']} untested · "
                f"{summary['disabled_tools']} disabled"
            )
            lines.append("A model appearing in Ollama metadata does not prove generation works.")
            self.call_from_thread(self._finish_diagnose, "\n".join(lines))
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_diagnose(self, report: str) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text(""))
        log.write(_panel(report, "NOVA DIAGNOSTICS", "yellow"))
        self._set_busy(False)
        self._set_status("Diagnostics complete · generation not tested")

    def _inspect(self, command: str) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        profile = runtime_profile(self.core)
        model = inspect_model(self.core)
        table = Table(show_header=False, expand=True, box=None, padding=(0, 1))
        table.add_column("field", style="dim")
        table.add_column("value")
        rows = [
            ("Identity", f"{profile['identity']} · {profile['developer']}"),
            ("Version", profile["version"]),
            ("Provider / model", f"{profile['provider']} · {profile['configured_model']}"),
            ("Python", f"{profile['implementation']} {profile['python']}"),
            ("Platform", profile["platform"]),
            ("Working directory", profile["working_directory"]),
            ("Context / output", f"{profile['context_budget']:,} / {profile['output_budget']:,}"),
            ("Tools enabled", f"{profile['enabled_tools']}/{profile['registered_tools']}"),
            ("Components present", f"{profile['present_components']}/{profile['component_count']}"),
            ("Model metadata", model["status"]),
            ("Parameter count", model["parameter_count"]),
            ("Reported size", model["parameter_size"]),
            ("Architecture", model["architecture"]),
            ("Quantization", model["quantization"]),
            ("Model context length", model["model_context_length"]),
            ("Capabilities", ", ".join(model["capabilities"]) or "Unknown"),
            ("Evidence", model["detail"]),
        ]
        for key, value in rows:
            table.add_row(key, str(value))
        self.call_from_thread(self._finish_inspection, command, table)

    def _finish_inspection(self, command: str, table: Table) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text(""))
        log.write(_panel(table, "NOVA SELF-INSPECTION" if command == "/self" else "OLLAMA MODEL"))
        self._set_busy(False)
        self._set_status("Metadata read complete · values are not guessed")

    def _reset_core(self) -> None:
        try:
            core = NovaCore(status_callback=self._status_from_core)
            self.call_from_thread(self._finish_reset, core)
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_reset(self, core: NovaCore) -> None:
        self.core = core
        self._refresh_sidebar()
        self._set_busy(False)
        self._set_status("New Nova session ready")

    def action_clear_chat(self) -> None:
        self._clear_transcript()

    def action_show_help(self) -> None:
        self._handle_command("/help")